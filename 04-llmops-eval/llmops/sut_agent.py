"""被测 Agent（system under test）：极简 Function Calling 循环。

给 03_eval_agent.py 当被测对象：模型自主决定调 search / calculator / get_time，
工具结果回填后继续，直到输出最终答案或超过 max_turns。
评估关注：任务是否成功（答案断言）+ 必调工具是否调了 + 用了几轮。
"""
from __future__ import annotations

import math
import re
from datetime import datetime

from llmops.llm import chat
from llmops.sut_rag import retrieve as _kb_search
from llmops.trace import Trace

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "在产品知识库中检索资料。传入中文关键词查询。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "检索关键词"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "计算一个数学表达式，如 (12+8)*3。支持 + - * / ** () 与 sqrt/sin/cos。",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string", "description": "数学表达式"}},
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": "获取当前日期与时间。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

SYSTEM = (
    "你是一个办事型助手。能用工具就先调用工具再回答；"
    "涉及产品问题用 search 查资料，涉及计算用 calculator，涉及时间用 get_time。"
    "最后用简洁中文给出结论。"
)


def _safe_calc(expr: str) -> str:
    """安全求值：白名单函数 + AST 无关的受限 eval。"""
    allowed = {"sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "abs": abs, "round": round}
    if not re.fullmatch(r"[\d\s+\-*/().,sqrtincosbaul_]*", expr):
        return "表达式含非法字符"
    try:
        return str(eval(expr, {"__builtins__": {}}, allowed))  # noqa: S307 —— 已白名单过滤
    except Exception as e:  # noqa: BLE001
        return f"计算错误: {e}"


def _execute_tool(name: str, args: dict) -> str:
    if name == "search":
        chunks = _kb_search(args.get("query", ""), k=3)
        if not chunks:
            return "（知识库无相关内容）"
        return "\n".join(f"- {c['content']}" for c in chunks)
    if name == "calculator":
        return _safe_calc(args.get("expression", "0"))
    if name == "get_time":
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
    return f"未知工具 {name}"


def run_agent(
    goal: str,
    max_turns: int = 6,
    trace: Trace | None = None,
) -> dict:
    """跑一个任务。返回 {answer, tool_calls: [name...], turns, error}。"""
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": goal}]
    tool_calls: list[str] = []
    answer = ""
    error = None

    for turn in range(1, max_turns + 1):
        try:
            msg = chat(messages, tools=TOOLS, temperature=0.0, trace=trace)
        except Exception as e:  # noqa: BLE001
            error = f"turn{turn} LLM失败: {type(e).__name__}: {e}"
            break

        if not msg.tool_calls:
            answer = (msg.content or "").strip()
            return {"answer": answer, "tool_calls": tool_calls, "turns": turn, "error": error}

        # 回填 assistant(tool_calls) + 各工具结果
        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ],
            }
        )
        import json

        for tc in msg.tool_calls:
            name = tc.function.name
            tool_calls.append(name)
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = _execute_tool(name, args)
            if trace is not None:
                with trace.span(f"tool:{name}", inputs=args):
                    pass  # latency 已覆盖；结构演示用
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    return {"answer": answer, "tool_calls": tool_calls, "turns": max_turns, "error": error}
