import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    mode: str = "demo"
    model: str = "qwen4-max"
    api_key: str = field(default="", repr=False)
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    output_dir: Path = ROOT / "output"
    weather_mode: str = "fixture"
    weather_key: str = field(default="", repr=False)
    amap_key: str = field(default="", repr=False)

    @classmethod
    def from_environment(cls):
        load_dotenv(ROOT / ".env")
        key = os.getenv("DASHSCOPE_API_KEY", "").strip()
        mode = os.getenv("ASSISTANT_MODE", "auto").strip().lower()
        if mode == "auto":
            mode = "qwen" if key else "demo"
        if mode not in {"qwen", "demo"}:
            raise ValueError("ASSISTANT_MODE must be auto, qwen, or demo")
        if mode == "qwen" and not key:
            raise ValueError("DASHSCOPE_API_KEY is not configured")
        base_url = os.getenv("DASHSCOPE_BASE_URL") or cls.base_url
        endpoint = urlsplit(base_url)
        host = endpoint.hostname or ""
        if key and (
            endpoint.scheme != "https"
            or endpoint.username
            or not (host == "dashscope.aliyuncs.com" or host.endswith(".cn-beijing.maas.aliyuncs.com"))
            or endpoint.path.rstrip("/") != "/compatible-mode/v1"
        ):
            raise ValueError("DASHSCOPE_BASE_URL must be a Beijing Bailian Chat Completions base URL")
        weather_mode = os.getenv("MCP_WEATHER_MODE", "fixture")
        if weather_mode not in {"fixture", "live"}:
            raise ValueError("MCP_WEATHER_MODE must be fixture or live")
        return cls(
            mode=mode,
            model=os.getenv("QWEN_MODEL") or cls.model,
            api_key=key,
            base_url=base_url,
            output_dir=Path(os.getenv("MCP_OUTPUT_DIR") or cls.output_dir).resolve(),
            weather_mode=weather_mode,
            weather_key=os.getenv("OPENWEATHER_API_KEY", "").strip(),
            amap_key=os.getenv("AMAP_MAPS_API_KEY", "").strip(),
        )
