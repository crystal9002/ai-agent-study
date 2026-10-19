"""第二步：CLI 版知识库助手 Agent（打印工具轨迹 + 带引用的回答）。

用法：
    .venv/bin/python scripts/02_kb_agent.py "团队版多少钱？50个人一年多少钱？"
    .venv/bin/python scripts/02_kb_agent.py            # 用内置示例问题
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from kba import KBAgent

DEFAULT_Q = "团队版多少钱？50个人一年多少钱？"


def _short(obj, limit: int = 220) -> str:
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"


def on_event(ev: dict) -> None:
    """把 Agent 的事件流打印成可读的工具轨迹（同一回调可复用到 Web 版）。"""
    kind = ev.get("type")
    if kind == "start":
        print(f"❓ 问题: {ev['question']}")
        print(f"🛠  可用工具: {', '.join(ev['tools'])}")
        print("-" * 60)
    elif kind == "tool_call":
        print(f"🔧 {ev['name']}({_short(ev['args'], 160)})")
    elif kind == "tool_result":
        result = ev["result"]
        # 检索结果单独展开，方便肉眼核对引用编号
        if ev["name"] == "search_kb" and result.get("results"):
            print(f"   ↩ 命中 {result['count']} 条：")
            for r in result["results"]:
                print(f"      [{r['n']}] {r['doc']} · {r['title']}  {_short(r['text'], 90)}")
        else:
            print(f"   ↩ {_short(result)}")
    elif kind == "final":
        print("-" * 60)
        print("📄 回答:\n")
        print(ev["content"])


def main() -> None:
    question = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_Q
    print("=" * 60)
    try:
        KBAgent().run(question, on_event=on_event)
    except Exception as e:  # noqa: BLE001 —— API/索引失败给出明确提示
        print(f"❌ 运行失败: {type(e).__name__}: {e}")
        print("请先运行 scripts/01_build_kb.py，并检查 .env 中的 "
              "OPENAI_BASE_URL / OPENAI_API_KEY / LLM_MODEL")


if __name__ == "__main__":
    main()
