import logging
import os

import httpx
from mcp.server.fastmcp import FastMCP


mcp = FastMCP("weather")
logging.getLogger("httpx").setLevel(logging.WARNING)
FIXTURES = {
    "北京": "北京：晴，18°C，东风 2 级。",
    "上海": "上海：多云，21°C，东南风 3 级。",
    "杭州": "杭州：小雨，17°C，东北风 2 级。",
}
CITY_NAMES = {"beijing": "北京", "shanghai": "上海", "hangzhou": "杭州"}
LIVE_CITY_NAMES = {chinese: english for english, chinese in CITY_NAMES.items()}


@mcp.tool()
async def query_weather(city: str) -> str:
    """查询指定城市的天气。实时查询优先传英文城市名，例如 Beijing。演示数据会明确标记。"""
    city = city.strip()
    if not city or len(city) > 80:
        raise ValueError("请提供有效的城市名")
    if os.getenv("MCP_WEATHER_MODE") != "live":
        city = CITY_NAMES.get(city.lower(), city)
        if city not in FIXTURES:
            raise ValueError("演示模式仅提供北京、上海和杭州")
        return "【演示天气】" + FIXTURES[city]

    key = os.getenv("OPENWEATHER_API_KEY")
    if not key:
        raise ValueError("实时天气服务尚未配置")
    if key.startswith("sk-"):
        raise ValueError("OPENWEATHER_API_KEY 需要使用 OpenWeather 凭据")
    weather_city = LIVE_CITY_NAMES.get(city.removesuffix("市"), city)
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"q": weather_city, "appid": key, "units": "metric", "lang": "zh_cn"},
            )
            response.raise_for_status()
            data = response.json()
            return f"{data['name']}：{data['weather'][0]['description']}，{data['main']['temp']}°C。"
    except (httpx.HTTPError, ValueError, KeyError, IndexError):
        raise ValueError("实时天气查询失败，请确认城市或稍后再试") from None


if __name__ == "__main__":
    mcp.run(transport="stdio")
