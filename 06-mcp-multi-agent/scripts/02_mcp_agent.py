"""② MCP Agent：手写 ReAct 循环 + 通过 MCP stdio 子进程挂载工具。

链路（与 docs/03 对应）：
  本进程 Agent 循环 --stdio(JSON-RPC)--> mcpd/server.py 子进程
      list_tools() → 转 OpenAI FC schema → 喂给 LLM
      LLM 决定调用 → call_tool() → 结果回填 → 继续思考

用法：
  python scripts/02_mcp_agent.py "50人团队版一年多少钱？"
  python scripts/02_mcp_agent.py            # 用默认问题
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from llm import LLM
from mcpd.client import SyncMCPBridge, mcp_tools_to_openai

DEFAULT_QUESTION = "我们团队 50 人，用团队版一年多少钱？有没有折扣？"

SYSTEM = """你是一个工具助手，通过 MCP 协议接入了外部工具。
规则：
1. 需要外部信息/计算时调用工具；能直接答就直接答。
2. 工具返回什么就基于什么回答，不编造数字。
3. 可以连续调用多个工具（比如先 search_kb 再 calc）。
4. 全程中文，结论里给出关键数字的来源（哪个工具返回的）。
5. 工具报错时换参数重试一次；仍失败则如实说明。"""

MAX_ITERS = 6


def truncate(text: str, limit: int = 200) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def main() -> None:
    question = sys.argv[1].strip() if len(sys.argv) > 1 else DEFAULT_QUESTION
    llm = LLM()
    bridge = SyncMCPBridge()

    print(f"❓ 问题: {question}\n")
    print("⏳ 启动 MCP server 子进程并握手 …")
    bridge.connect()
    mcp_tools = bridge.list_tools()
    fc_tools = mcp_tools_to_openai(mcp_tools)
    print(f"🔌 已通过 MCP 发现 {len(mcp_tools)} 个工具: "
          f"{', '.join(t['name'] for t in mcp_tools)}\n")

    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": question},
    ]
    try:
        for it in range(1, MAX_ITERS + 1):
            msg = llm.chat(messages, tools=fc_tools)
            messages.append(LLM.to_message(msg))

            if not msg.tool_calls:
                print(f"\n💬 最终回答:\n{msg.content}")
                return

            for tc in msg.tool_calls:
                name, raw_args = tc.function.name, tc.function.arguments
                print(f"  [iter {it}] 🔧 MCP 调用 → {name}({truncate(raw_args, 120)})")
                try:
                    args = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError:
                    args = {}
                # 关键一步：OpenAI 的 tool_call → MCP 的 call_tool → 结果回填
                result = bridge.call_tool(name, args)
                print(f"           ↩ {truncate(json.dumps(result, ensure_ascii=False))}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

        print(f"\n⚠️ 超过最大轮数 {MAX_ITERS}，强制收尾")
        msg = llm.chat(messages)
        print(f"\n💬 最终回答（可能不完整）:\n{msg.content}")
    finally:
        bridge.close()
        print("\n🔌 MCP 子进程已关闭")


if __name__ == "__main__":
    main()
