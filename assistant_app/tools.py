import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Literal

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .amap import AMAP_TOOLS, ROUTE_TOOLS, connect_amap
from .settings import ROOT, Settings


logger = logging.getLogger(__name__)
ToolStatus = Literal["ok", "error", "unavailable", "blocked"]


@dataclass(frozen=True)
class Server:
    name: str
    module: str = ""
    env: dict[str, str] = field(default_factory=dict, repr=False)
    amap_key: str = field(default="", repr=False)


@dataclass
class ToolResult:
    tool: str
    service: str
    status: ToolStatus
    elapsed_ms: int
    content: str


def local_servers(settings: Settings) -> tuple[Server, ...]:
    weather = {"MCP_WEATHER_MODE": settings.weather_mode}
    if settings.weather_mode == "live" and settings.weather_key:
        weather["OPENWEATHER_API_KEY"] = settings.weather_key
    servers = (
        Server("weather", "assistant_app.servers.weather", weather),
        Server("notes", "assistant_app.servers.notes", {"MCP_OUTPUT_DIR": str(settings.output_dir)}),
    )
    if settings.amap_key and settings.mode == "qwen":
        servers += (Server("amap", amap_key=settings.amap_key),)
    return servers


@asynccontextmanager
async def connect(server: Server):
    if server.amap_key:
        async with connect_amap(server.amap_key) as client:
            yield client
        return
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", server.module],
        env={"PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", **server.env},
        cwd=str(ROOT),
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            yield client


class Tools:
    def __init__(self, servers: tuple[Server, ...]):
        self.servers = servers
        self.health: dict[str, str] = {}
        self.registry = {}

    async def discover(self) -> None:
        async def discover_one(server: Server):
            try:
                async with asyncio.timeout(12):
                    async with connect(server) as client:
                        discovered = (await client.list_tools()).tools
                        if server.amap_key:
                            discovered = [tool for tool in discovered if tool.name in AMAP_TOOLS]
                            if not any(tool.name in ROUTE_TOOLS for tool in discovered):
                                return server, None
                        return server, discovered
            except Exception as exc:
                logger.warning("MCP discovery failed for %s (%s)", server.name, type(exc).__name__)
                return server, None

        for server, tools in await asyncio.gather(*(discover_one(server) for server in self.servers)):
            self.health[server.name] = "ready" if tools else "unavailable"
            for tool in tools or []:
                if tool.name in self.registry:
                    logger.warning("Duplicate MCP tool ignored: %s", tool.name)
                    continue
                self.registry[tool.name] = (server, tool)

    def schemas(self, allow_save: bool) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {"name": tool.name, "description": tool.description or "", "parameters": tool.inputSchema},
            }
            for _, tool in self.registry.values()
            if allow_save or tool.name != "save_note"
        ]

    async def call(self, name: str, arguments: dict) -> ToolResult:
        registered = self.registry.get(name)
        if not registered:
            service = "amap" if name in AMAP_TOOLS else {"query_weather": "weather", "save_note": "notes"}.get(
                name, "unknown"
            )
            return ToolResult(name, service,
                              "unavailable", 0, "工具暂不可用")
        server, _ = registered
        started = perf_counter()
        try:
            async with asyncio.timeout(12):
                async with connect(server) as client:
                    result = await client.call_tool(name, arguments)
            content = "\n".join(block.text for block in result.content if block.type == "text").strip()
            if server.amap_key:
                content = content.replace(server.amap_key, "[已隐藏]")
            status: ToolStatus = "error" if result.isError or not content else "ok"
        except Exception as exc:
            logger.warning("MCP call failed for %s (%s)", name, type(exc).__name__)
            status = "error"
            content = ""
        if status != "ok":
            content = "工具执行失败，请检查输入或服务状态"
        return ToolResult(name, server.name, status, round((perf_counter() - started) * 1000), content)
