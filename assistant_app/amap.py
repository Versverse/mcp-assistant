from contextlib import asynccontextmanager

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


AMAP_ENDPOINT = "https://mcp.amap.com/mcp"
AMAP_TOOLS = frozenset({
    "maps_geo",
    "maps_text_search",
    "maps_direction_walking",
    "maps_direction_driving",
    "maps_direction_transit_integrated",
    "maps_schema_navi",
})
ROUTE_TOOLS = frozenset(tool for tool in AMAP_TOOLS if tool.startswith("maps_direction_"))


class AmapTransport(httpx.AsyncHTTPTransport):
    def __init__(self, api_key: str):
        super().__init__()
        self.api_key = api_key

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url != AMAP_ENDPOINT:
            raise httpx.RequestError("Unexpected Amap endpoint", request=request)
        # Add the credential at the transport boundary, after MCP builds its request.
        # Restore the original URL before HTTPX logs or reports the response.
        request.url = url.copy_add_param("key", self.api_key)
        try:
            return await super().handle_async_request(request)
        finally:
            request.url = url


@asynccontextmanager
async def connect_amap(api_key: str):
    if api_key.startswith("sk-"):
        raise ValueError("AMAP_MAPS_API_KEY requires an Amap credential")
    async with httpx.AsyncClient(transport=AmapTransport(api_key), timeout=10) as http_client:
        async with streamable_http_client(AMAP_ENDPOINT, http_client=http_client) as (read, write, _):
            async with ClientSession(read, write) as client:
                await client.initialize()
                yield client
