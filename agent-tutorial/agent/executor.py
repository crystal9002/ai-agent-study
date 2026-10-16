"""执行器：单步的 ReAct 循环（Reason → Act → Observe，直到给出结论）。

这是 Agent 最核心的运行时：
  LLM 思考要不要调工具 → 调工具 → 观察结果 → 再思考 …… → 输出本步结论
循环靠"模型自己决定何时停止"，工程上必须加上限（max_iters）防跑飞。
"""
from __future__ import annotations

import json

from .llm import LLM
from .tools import ToolRegistry

STEP_SYSTEM = """你是一个任务执行助手，负责完成任务规划中的【当前步骤】。

规则：
1. 先判断完成本步需要什么信息，选择合适的工具获取数据；能直接回答就不用工具。
2. 工具返回结果后，基于真实数据分析，不要编造数据。
3. 需要多次调用工具就继续调用（可组合多个工具的结果）。
4. 本步彻底完成后，输出简明的结论（含关键数据），不要输出"我将继续调用"之类的过程性描述。
5. 如果工具报错，换一种参数或方法重试；确实无法完成时明确说明原因。
6. 全程用中文。"""

STEP_TEMPLATE = """【总任务目标】
{goal}

【已完成的步骤及结果】
{history}

【当前步骤】（第 {step_id} 步）
{step_goal}

请完成当前步骤。"""


def _truncate(text: str, limit: int = 800) -> str:
    return text if len(text) <= limit else text[:limit] + "…(截断)"


def run_step(
    llm: LLM,
    registry: ToolRegistry,
    goal: str,
    step_id: int,
    step_goal: str,
    history: list[str],
    max_iters: int = 6,
) -> str:
    """执行一个规划步骤，返回该步骤的结论文本。"""
    history_text = "\n".join(f"- { _truncate(h) }" for h in history) or "（暂无）"
    messages: list[dict] = [
        {"role": "system", "content": STEP_SYSTEM},
        {"role": "user", "content": STEP_TEMPLATE.format(
            goal=goal, history=history_text, step_id=step_id, step_goal=step_goal)},
    ]

    for _ in range(max_iters):
        msg = llm.chat(messages, tools=registry.specs())
        messages.append(LLM.to_message(msg))

        if not msg.tool_calls:
            return (msg.content or "").strip() or "（执行者未返回结论）"

        # ① Act：执行工具 ② Observe：结果作为 tool 角色回填，进入下一轮思考
        for tc in msg.tool_calls:
            result = registry.invoke(tc.function.name, tc.function.arguments)
            print(f"    🔧 {tc.function.name}({tc.function.arguments[:80]}) → "
                  f"{_truncate(json.dumps(result, ensure_ascii=False), 120)}")
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

    return f"（本步执行失败：超过最大工具调用轮数 {max_iters}）"
