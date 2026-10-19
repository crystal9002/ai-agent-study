"""框架版：LangGraph 实现同一个知识库助手（生产写法对照）。

对应原生版逐环节：
    kba/kb.py     → 原样复用（检索层与框架无关，@tool 只做包装）
    kba/tools.py  → @tool 装饰器（Schema 仍由签名 + docstring 自动推导）
    kba/llm.py    → ChatOpenAI(base_url/api_key/model 读 .env)
    kba/agent.py  → create_react_agent（手写 ReAct 循环的框架等价物）

用法：
    pip install -r requirements-framework.txt
    .venv/bin/python scripts/04_langgraph.py "团队版多少钱？50个人一年多少钱？"
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

try:
    from langchain_core.tools import tool
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent
except ImportError as e:  # 缺依赖时给出可直接复制的修复命令
    print(f"❌ 缺少框架依赖: {e}")
    print("请先安装：.venv/bin/python -m pip install -r requirements-framework.txt")
    sys.exit(1)

from kba.agent import SYSTEM
from kba.tools import calc, list_notes, search_kb, write_note

DEFAULT_Q = "团队版多少钱？50个人一年多少钱？"

# 同一份业务函数套上 LangChain @tool：Schema 由签名与 docstring 推导，
# search_kb 底层调的还是 kba/kb.py —— 检索层一份，两种写法共用
tools = [tool(search_kb), tool(calc), tool(write_note), tool(list_notes)]

llm = ChatOpenAI(
    model=os.getenv("LLM_MODEL", "deepseek-chat"),
    base_url=os.getenv("OPENAI_BASE_URL"),
    api_key=os.getenv("OPENAI_API_KEY"),
    temperature=0.2,
)


def main() -> None:
    question = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_Q
    print(f"❓ 问题: {question}")
    print("-" * 60)
    try:
        app = create_react_agent(llm, tools, prompt=SYSTEM)
        result = app.invoke({"messages": [("human", question)]})
    except Exception as e:  # noqa: BLE001
        print(f"❌ 运行失败: {type(e).__name__}: {e}")
        print("请检查 .env 配置与 requirements-framework.txt 依赖")
        return

    # 消息历史里既有 AI 的 tool_calls，也有 tool 结果 → 打印成与 CLI 同款轨迹
    for msg in result["messages"]:
        if getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                print(f"🔧 {tc['name']}({str(tc.get('args', ''))[:160]})")
        elif msg.type == "tool":
            print(f"   ↩ {str(msg.content)[:200]}")
    print("-" * 60)
    print("📄 回答:\n")
    print(result["messages"][-1].content)


if __name__ == "__main__":
    main()
