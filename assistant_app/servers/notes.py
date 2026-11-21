import os
from pathlib import Path
from uuid import uuid4

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("notes")


@mcp.tool()
def save_note(content: str) -> str:
    """将文本保存到专用输出目录，返回新创建的文件名。"""
    text = content.strip()
    if not text or len(text) > 12_000:
        raise ValueError("笔记需包含 1 至 12000 个字符")
    directory = Path(os.getenv("MCP_OUTPUT_DIR", "output"))
    directory.mkdir(parents=True, exist_ok=True)
    name = f"note_{uuid4().hex}.txt"
    with (directory / name).open("x", encoding="utf-8") as note:
        note.write(text + "\n")
    return name


if __name__ == "__main__":
    mcp.run(transport="stdio")
