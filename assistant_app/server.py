import asyncio
import logging
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, StringConstraints

from .settings import Settings
from .tools import Server, ToolResult, Tools, local_servers


logger = logging.getLogger(__name__)
SAVE = re.compile(r"保存|记下|写入|\bsave\b", re.IGNORECASE)
NOTE = re.compile(r"^(?:保存|写入)\s*[：:]\s*(.+)", re.DOTALL)
NO_SAVE = re.compile(r"不要|不用|无需|不需要|不必|别保存|怎么保存|如何保存|\b(?:not|never|how to)\b", re.IGNORECASE)
CITIES = {"北京": "北京", "上海": "上海", "杭州": "杭州", "beijing": "北京", "shanghai": "上海", "hangzhou": "杭州"}


@dataclass
class Session:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    previous_message: str = ""
    weather_summary: str = ""


class ChatRequest(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    thread_id: UUID | None = None


class ChatReply(BaseModel):
    thread_id: UUID
    content: str
    trace: list[ToolResult]


def write_requested(text: str) -> bool:
    return bool(NOTE.match(text) or (SAVE.search(text) and not NO_SAVE.search(text)))


async def demo_reply(text: str, session: Session, tools: Tools) -> tuple[str, list[ToolResult]]:
    replies = []
    trace = []
    if "上一条" in text:
        return (
            f"你上一条消息是：{session.previous_message}" if session.previous_message else "当前会话还没有上一条消息。",
            trace,
        )
    save = write_requested(text)
    explicit = NOTE.match(text)
    wants_weather = "天气" in text and not explicit and not ("刚才" in text and save)
    if wants_weather:
        session.weather_summary = ""
        city = next((name for key, name in CITIES.items() if key in text.lower()), None)
        if city is None:
            return "请选择演示城市：北京、上海或杭州。", trace
        result = await tools.call("query_weather", {"city": city})
        trace.append(result)
        if result.status != "ok":
            return "天气工具暂不可用。你仍然可以要求保存一条手写笔记。", trace
        session.weather_summary = result.content
        replies.append(result.content)
    if save:
        content = explicit[1].strip() if explicit else session.weather_summary
        if not content:
            return "请提供笔记内容，例如「保存：出门带伞」。", trace
        result = await tools.call("save_note", {"content": content})
        trace.append(result)
        replies.append(f"已保存：`{result.content}`" if result.status == "ok" else "笔记工具暂不可用，未能保存。")
    return "\n\n".join(replies) or "演示指令：查北京天气并保存摘要，或输入「保存：出门带伞」。", trace


def create_app(*, config: Settings | None = None, servers: tuple[Server, ...] | None = None) -> FastAPI:
    sessions: dict[UUID, Session] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = config or Settings.from_environment()
        tools = Tools(local_servers(settings) if servers is None else servers)
        await tools.discover()
        app.state.settings = settings
        app.state.tools = tools
        app.state.agent = None
        if settings.mode == "qwen":
            from .qwen import build_qwen_agent

            app.state.agent = build_qwen_agent(settings, tools)
        yield

    app = FastAPI(title="MCP 多工具助手", lifespan=lifespan)

    @app.get("/health")
    async def health():
        settings = app.state.settings
        return {
            "status": "ready",
            "mode": settings.mode,
            "model": settings.model if settings.mode == "qwen" else None,
            "weather_mode": settings.weather_mode,
            "services": app.state.tools.health,
        }

    @app.post("/chat", response_model=ChatReply)
    async def chat(request: ChatRequest):
        thread_id = request.thread_id
        if thread_id is None:
            thread_id = uuid4()
            sessions[thread_id] = Session()
        elif thread_id not in sessions:
            raise HTTPException(404, detail="会话已失效，请开始新会话")
        session = sessions[thread_id]
        async with session.lock:
            if app.state.agent is None:
                content, trace = await demo_reply(request.message, session, app.state.tools)
            else:
                try:
                    allow_save = write_requested(request.message)
                    save_tool_result = allow_save and not NOTE.match(request.message)
                    result = await app.state.agent.ainvoke(
                        {
                            "messages": [{"role": "user", "content": request.message}],
                            "allow_save": allow_save,
                            "require_weather": save_tool_result and bool(
                                re.search(r"(?:查|看看|获取).*天气|\bweather\b", request.message, re.IGNORECASE)
                            ),
                            "require_route": save_tool_result and bool(
                                re.search(r"路线|导航|怎么走|\b(?:route|directions)\b", request.message, re.IGNORECASE)
                            ),
                            "trace": [],
                            "rounds": 0,
                        },
                        {"configurable": {"thread_id": str(thread_id)}},
                    )
                    content = result["messages"][-1].content
                    if not isinstance(content, str) or not content.strip():
                        raise ValueError("empty assistant reply")
                    trace = result["trace"]
                except Exception as exc:
                    logger.warning("Qwen turn failed (%s)", type(exc).__name__)
                    raise HTTPException(502, detail="模型请求失败，请检查配置或稍后再试") from None
            session.previous_message = request.message
        return ChatReply(thread_id=thread_id, content=content, trace=trace)

    return app


app = create_app()
