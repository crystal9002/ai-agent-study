"""任务规划器：把模糊目标分解成有序步骤（Plan-and-Execute 模式的 Plan 阶段）。

规划的收益：
1. 先想清楚再动手，避免"走一步看一步"的盲目工具调用
2. 步骤可见 → 用户能提前确认/否决（human-in-the-loop 的插入点）
3. 每步独立执行 → 上下文不会因超长对话而失焦
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .llm import LLM

PLAN_SYSTEM = """你是一个任务规划助手。把用户的任务目标分解为有序的执行步骤。

要求：
1. 输出 3~6 个步骤，每步是可独立执行的具体动作（明确对象、参数与期望产出）。
2. 步骤之间按顺序依赖，编号从 1 开始。
3. tools 填写执行该步最可能用到的工具名（可为空数组，执行者可自行调整）。
4. 只输出一个 JSON 对象，不要任何解释文字。格式：
{"steps": [{"id": 1, "goal": "...", "tools": ["..."]}, ...]}"""


@dataclass
class Step:
    id: int
    goal: str
    tools: list[str] = field(default_factory=list)


@dataclass
class Plan:
    goal: str
    steps: list[Step]

    def render(self) -> str:
        lines = [f"{s.id}. {s.goal}" + (f"  (候选工具: {', '.join(s.tools)})" if s.tools else "")
                 for s in self.steps]
        return "\n".join(lines)


def _extract_json(text: str) -> dict:
    """LLM 输出难免带代码块围栏，取第一个 { 到最后一个 } 之间的内容。"""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"规划输出不是 JSON: {text[:200]}")
    return json.loads(text[start : end + 1])


def create_plan(llm: LLM, goal: str) -> Plan:
    msg = llm.chat([
        {"role": "system", "content": PLAN_SYSTEM},
        {"role": "user", "content": f"任务目标：{goal}"},
    ])
    data = _extract_json(msg.content or "")
    steps = [
        Step(id=int(s.get("id", i + 1)), goal=str(s.get("goal", "")),
             tools=[str(t) for t in s.get("tools", [])])
        for i, s in enumerate(data.get("steps", []))
    ]
    if not steps:
        raise ValueError("规划结果为空")
    return Plan(goal=goal, steps=steps)
