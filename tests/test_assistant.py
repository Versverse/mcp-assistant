import asyncio
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from assistant_app.amap import AMAP_ENDPOINT
from assistant_app.qwen import build_qwen_agent
from assistant_app.server import create_app
from assistant_app.servers.weather import query_weather
from assistant_app.settings import Settings
from assistant_app.tools import Server, Tools, local_servers


class AssistantTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory(prefix="mcp-assistant-"))
        self.config = Settings(output_dir=Path(directory))

    def client(self, servers=None):
        return self.enterContext(TestClient(create_app(config=self.config, servers=servers)))

    def chat(self, client, message, thread_id=None):
        response = client.post("/chat", json={"message": message, "thread_id": thread_id})
        self.assertEqual(response.status_code, 200, response.json())
        return response.json()

    def test_weather_then_save(self):
        client = self.client()
        self.assertEqual(client.get("/health").json()["services"], {"weather": "ready", "notes": "ready"})
        response = self.chat(client, "查北京天气并保存摘要")
        self.assertEqual(
            [(step["tool"], step["status"]) for step in response["trace"]],
            [("query_weather", "ok"), ("save_note", "ok")],
        )
        filename = response["trace"][1]["content"]
        self.assertIn("【演示天气】北京", (self.config.output_dir / filename).read_text(encoding="utf-8"))

    def test_query_without_writing(self):
        client = self.client()
        response = self.chat(client, "查上海天气，不要保存")
        self.assertEqual([step["tool"] for step in response["trace"]], ["query_weather"])
        self.assertFalse(list(self.config.output_dir.glob("*.txt")))

    def test_parallel_sessions_do_not_mix_messages(self):
        client = self.client()
        with ThreadPoolExecutor(max_workers=2) as executor:
            first, second = executor.map(
                lambda message: self.chat(client, message),
                ("保存：只在甲会话。确认天气前不要出门。", "保存：只在乙会话"),
            )
        self.assertNotEqual(first["thread_id"], second["thread_id"])
        self.assertNotEqual(first["trace"][0]["content"], second["trace"][0]["content"])
        self.assertEqual(len(list(self.config.output_dir.glob("*.txt"))), 2)
        review = self.chat(client, "我上一条说的是什么", first["thread_id"])["content"]
        self.assertIn("只在甲会话", review)
        self.assertNotIn("只在乙会话", review)
        missing = client.post("/chat", json={"message": "继续", "thread_id": str(uuid4())})
        self.assertEqual(missing.status_code, 404)

    def test_weather_service_down_does_not_disable_notes(self):
        _, notes = local_servers(self.config)
        client = self.client((Server("weather", "assistant_app.servers.unavailable"), notes))
        self.assertEqual(
            client.get("/health").json()["services"], {"weather": "unavailable", "notes": "ready"}
        )
        failed = self.chat(client, "查杭州天气并保存摘要")
        self.assertEqual([(step["tool"], step["status"]) for step in failed["trace"]],
                         [("query_weather", "unavailable")])
        self.assertFalse(list(self.config.output_dir.glob("*.txt")))
        saved = self.chat(client, "保存：出门带伞", failed["thread_id"])
        self.assertEqual(saved["trace"][0]["status"], "ok")

    def test_new_weather_failure_does_not_reuse_old_result(self):
        client = self.client()
        queried = self.chat(client, "查北京天气")
        self.chat(client, "查南京天气", queried["thread_id"])
        response = self.chat(client, "保存刚才的天气", queried["thread_id"])
        self.assertEqual(response["trace"], [])
        self.assertFalse(list(self.config.output_dir.glob("*.txt")))


class ScriptedModel:
    def __init__(self, *messages):
        self.replies = iter(messages)

    def bind_tools(self, schemas, *, parallel_tool_calls):
        return self

    async def ainvoke(self, messages):
        return next(self.replies)


def tool_call(name, **arguments):
    return AIMessage(content="", tool_calls=[{"name": name, "args": arguments, "id": uuid4().hex}])


class ModelWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_weather_rejects_model_credentials_before_opening_http_client(self):
        with patch.dict("os.environ", {"MCP_WEATHER_MODE": "live", "OPENWEATHER_API_KEY": "sk-test-only"}):
            with patch("assistant_app.servers.weather.httpx.AsyncClient") as http_client:
                with self.assertRaisesRegex(ValueError, "OpenWeather"):
                    await query_weather("Beijing")
                http_client.assert_not_called()

    async def test_live_weather_accepts_a_known_city_in_chinese(self):
        def reply(request):
            self.assertEqual(request.url.params["q"], "beijing")
            return httpx.Response(200, json={
                "name": "Beijing", "weather": [{"description": "晴"}], "main": {"temp": 10}
            })

        client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
        with patch.dict("os.environ", {"MCP_WEATHER_MODE": "live", "OPENWEATHER_API_KEY": "weather-test-key"}):
            with patch("assistant_app.servers.weather.httpx.AsyncClient", return_value=client):
                result = await query_weather("北京市")
        self.assertIn("10°C", result)

    async def test_qwen_chat_completions_request(self):
        settings = Settings(mode="qwen", api_key="test-only")
        tools = Tools(local_servers(settings))
        await tools.discover()
        received = []

        def reply(request):
            received.append((request.url, json.loads(request.content)))
            return httpx.Response(200, json={
                "id": "local-test", "object": "chat.completion", "created": 1, "model": settings.model,
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": "测试回复"}}],
            })

        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as http_client:
            with patch("assistant_app.qwen.ChatOpenAI",
                       side_effect=lambda **options: ChatOpenAI(**options, http_async_client=http_client)):
                agent = build_qwen_agent(settings, tools)
            result = await agent.ainvoke(
                {"messages": [{"role": "user", "content": "你好"}],
                 "allow_save": False, "require_weather": False, "trace": [], "rounds": 0},
                {"configurable": {"thread_id": str(uuid4())}},
            )
        self.assertEqual(result["messages"][-1].content, "测试回复")
        self.assertEqual(len(received), 1)
        url, body = received[0]
        self.assertEqual(url.path, "/compatible-mode/v1/chat/completions")
        self.assertEqual(body["model"], "qwen4-max")
        self.assertFalse(body["enable_thinking"])
        self.assertFalse(body["parallel_tool_calls"])
        self.assertFalse(body["stream"])
        self.assertEqual([item["function"]["name"] for item in body["tools"]], ["query_weather"])

    async def test_workflow_executes_real_tools_in_order(self):
        with tempfile.TemporaryDirectory(prefix="mcp-workflow-") as directory:
            settings = Settings(output_dir=Path(directory))
            tools = Tools(local_servers(settings))
            await tools.discover()
            agent = build_qwen_agent(settings, tools, model=ScriptedModel(
                tool_call("query_weather", city="上海"),
                tool_call("save_note", content="【演示天气】上海：多云"),
                AIMessage(content="已查询并保存"),
            ))
            turn = await agent.ainvoke(
                {"messages": [{"role": "user", "content": "查上海天气并保存摘要"}],
                 "allow_save": True, "require_weather": True, "trace": [], "rounds": 0},
                {"configurable": {"thread_id": str(uuid4())}},
            )
            self.assertEqual([step["status"] for step in turn["trace"]], ["ok", "ok"])
            self.assertEqual(len(list(settings.output_dir.glob("*.txt"))), 1)

    async def test_amap_workflow_discovers_and_executes_route_and_navigation(self):
        fake_key = uuid4().hex
        calls = []
        allowed = {
            "maps_geo": {"address": "string"},
            "maps_direction_walking": {"origin": "string", "destination": "string"},
            "maps_schema_navi": {"lon": "string", "lat": "string"},
            "maps_schema_take_taxi": {},
        }

        async def respond(_, request):
            self.assertEqual(request.url.copy_with(query=None), AMAP_ENDPOINT)
            self.assertEqual(request.url.params.get("key"), fake_key)
            message = json.loads(request.content)
            method = message["method"]
            if method == "notifications/initialized":
                return httpx.Response(202)
            if method == "initialize":
                result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "test-amap", "version": "1"}}
            elif method == "tools/list":
                result = {"tools": [
                    {"name": name, "inputSchema": {"type": "object", "properties": {
                        arg: {"type": kind} for arg, kind in parameters.items()
                    }, "required": list(parameters)}} for name, parameters in allowed.items()
                ]}
            else:
                self.assertEqual(method, "tools/call")
                tool = message["params"]["name"]
                calls.append(tool)
                result = {"content": [{"type": "text", "text": {
                    "maps_geo": "116.39,39.91",
                    "maps_direction_walking": "步行 1200 米",
                    "maps_schema_navi": "amapuri://navi?lon=116.40&lat=39.92",
                }[tool]}]}
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": result})

        settings = Settings(mode="qwen", amap_key=fake_key)
        tools = Tools(tuple(server for server in local_servers(settings) if server.name == "amap"))
        with patch.object(httpx.AsyncHTTPTransport, "handle_async_request", respond):
            with self.assertLogs("httpx", level="INFO") as logs:
                await tools.discover()
                self.assertEqual(tools.health, {"amap": "ready"})
                self.assertNotIn("maps_schema_take_taxi", tools.registry)
                agent = build_qwen_agent(settings, tools, model=ScriptedModel(
                    tool_call("maps_geo", address="北京市天安门"),
                    tool_call("maps_geo", address="北京市王府井"),
                    tool_call("maps_direction_walking", origin="116.39,39.91", destination="116.40,39.92"),
                    tool_call("maps_schema_navi", lon="116.40", lat="39.92"),
                    AIMessage(content="已查询路线并生成链接"),
                ))
                turn = await agent.ainvoke(
                    {"messages": [{"role": "user", "content": "查步行路线并给我导航链接"}],
                     "allow_save": False, "require_weather": False, "trace": [], "rounds": 0},
                    {"configurable": {"thread_id": str(uuid4())}},
                )
        self.assertEqual(calls, ["maps_geo", "maps_geo", "maps_direction_walking", "maps_schema_navi"])
        self.assertEqual([step["status"] for step in turn["trace"]], ["ok"] * 4)
        self.assertIn("amapuri://navi", turn["trace"][-1]["content"])
        self.assertNotIn(fake_key, "\n".join(logs.output))

    async def test_workflow_blocks_write_without_permission_or_weather(self):
        async def check(allow_save, require_weather):
            settings = Settings()
            tools = Tools(())
            agent = build_qwen_agent(settings, tools, model=ScriptedModel(
                tool_call("save_note", content="提前写文件"),
                AIMessage(content="未保存"),
            ))
            turn = await agent.ainvoke(
                {"messages": [{"role": "user", "content": "查询天气"}],
                 "allow_save": allow_save, "require_weather": require_weather, "trace": [], "rounds": 0},
                {"configurable": {"thread_id": str(uuid4())}},
            )
            self.assertEqual(turn["trace"][0]["status"], "blocked")

        await asyncio.gather(check(False, False), check(True, True))
