"""① 独立启动 MCP server：列出已注册工具清单，然后保持 stdio 服务进程。

用途：
  - 快速确认 server 能正常注册工具（不依赖客户端）
  - 作为后台常驻进程（真实场景中由客户端/Claude Desktop 拉起）

注意：本脚本 stdout 是 MCP 协议通道！所以清单打印走 stderr，
      任何第三方库误写 stdout 都会污染 JSON-RPC——这是 stdio 传输的第一纪律。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from mcpd.server import mcp


async def list_and_print() -> None:
    tools = await mcp.list_tools()
    print("📋 已注册工具（stdio server 即将启动，Ctrl+C 退出）:", file=sys.stderr)
    for t in tools:
        schema = getattr(t, "inputSchema", None) or t.input_schema  # mcp 2.x 改名
        params = ", ".join(schema.get("properties", {}).keys())
        print(f"  - {t.name}({params})", file=sys.stderr)
        print(f"      {t.description}", file=sys.stderr)


if __name__ == "__main__":
    # 先在一个临时 loop 里列举工具打印（纯展示，不进入服务循环）
    asyncio.run(list_and_print())
    try:
        # mcp.run 内部自带 anyio 事件循环，不能再套 asyncio.run
        mcp.run(transport="stdio")
    except KeyboardInterrupt:
        print("\nserver 已退出", file=sys.stderr)
