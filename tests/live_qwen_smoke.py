import argparse
import json
import re
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from fastapi.testclient import TestClient

from assistant_app.amap import ROUTE_TOOLS
from assistant_app.server import create_app
from assistant_app.settings import Settings


AMAP_LINK = re.compile(r"(?:amapuri://navi\?|https://uri\.amap\.com/navigation\?)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-weather", action="store_true", help="用 OpenWeather 查询真实天气")
    parser.add_argument("--amap", action="store_true", help="用高德查询步行路线和导航链接")
    args = parser.parse_args()
    settings = Settings.from_environment()
    if not settings.api_key:
        print("DASHSCOPE_API_KEY 未配置。")
        return 2
    if args.amap and not settings.amap_key:
        print("AMAP_MAPS_API_KEY 未配置。")
        return 2
    if args.live_weather and not settings.weather_key:
        print("OPENWEATHER_API_KEY 未配置。")
        return 2

    with TemporaryDirectory(prefix="mcp-qwen-smoke-") as directory:
        settings = replace(
            settings, mode="qwen", weather_mode="live" if args.live_weather else "fixture",
            amap_key=settings.amap_key if args.amap else "", output_dir=Path(directory),
        )
        with TestClient(create_app(config=settings)) as client:
            if args.amap and client.get("/health").json()["services"].get("amap") != "ready":
                print("高德 MCP 服务未能发现可用的路线工具。")
                return 1
            message = "查询北京市的实时天气，并将查询结果保存成笔记。" if args.live_weather else (
                "查北京天气并保存摘要。请在笔记里注明这是演示天气。"
            )
            if args.amap:
                message = "查询从北京市天安门到王府井的步行路线，并提供高德 App 导航链接。"
            started = perf_counter()
            response = client.post("/chat", json={"message": message})
            if response.status_code != 200:
                print(f"联调失败，HTTP {response.status_code}。")
                return 1
            trace = response.json()["trace"]
            steps = [(step["tool"], step["status"]) for step in trace]
            if args.amap:
                route_ok = any(
                    step["tool"] in ROUTE_TOOLS and step["status"] == "ok"
                    and any(word in step["content"].lower() for word in ("distance", "duration", "距离", "米"))
                    for step in trace
                )
                navigation_ok = any(
                    step["tool"] == "maps_schema_navi" and step["status"] == "ok"
                    and AMAP_LINK.search(step["content"]) for step in trace
                )
                print(json.dumps({"model": settings.model, "steps": steps, "route_verified": route_ok,
                                  "navigation_verified": navigation_ok,
                                  "elapsed_ms": round((perf_counter() - started) * 1000)}, ensure_ascii=False))
                return 0 if route_ok and navigation_ok else 1
            files = list(settings.output_dir.glob("note_*.txt"))
            note = files[0].read_text(encoding="utf-8").lower() if len(files) == 1 else ""
            saved = "北京" in note or "beijing" in note
            weather_verified = any(
                step["tool"] == "query_weather" and step["status"] == "ok" and "°C" in step["content"]
                for step in trace
            )
            if args.live_weather:
                saved = saved and any(unit in note for unit in ("°c", "℃", "摄氏度"))
            print(json.dumps({
                "model": settings.model,
                "steps": steps,
                "weather_verified": weather_verified,
                "note_verified": saved,
                "elapsed_ms": round((perf_counter() - started) * 1000),
            }, ensure_ascii=False))
            return 0 if steps == [("query_weather", "ok"), ("save_note", "ok")] and weather_verified and saved else 1


if __name__ == "__main__":
    raise SystemExit(main())
