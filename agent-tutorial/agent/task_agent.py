"""任务规划型 Agent 编排：规划 → 逐步执行 → 汇总（Plan-and-Execute）。

完整链路：
  目标 ──规划──→ Plan[step1..n]
                   │ 逐步交给执行器（每步内部是 ReAct 循环）
                   ▼
              步骤结果累积（作为后续步骤的上下文）
                   │
                   ▼
                 汇总生成最终行程方案
"""
from __future__ import annotations

from .executor import run_step
from .llm import LLM
from .planner import Plan, create_plan
from .tools import ToolRegistry, register_default_tools

SUMMARY_SYSTEM = """你是差旅规划专家。请根据任务目标与各步骤的执行结果，
整合出一份完整、可直接使用的行程方案（Markdown 格式），要求：
1. 覆盖：行程概览、交通、住宿、天气提醒、日程表、费用预估。
2. 只使用执行结果中出现的真实数据（航班号、价格、酒店名等），标注来源步骤编号。
3. 如果某步骤执行失败，如实说明该部分缺失，不要编造。
4. 最后附一段简短的"风险与建议"。"""

SUMMARY_TEMPLATE = """【任务目标】
{goal}

【执行计划】
{plan}

【各步骤执行结果】
{results}

请输出最终行程方案（Markdown）。"""


class TaskAgent:
    def __init__(self, max_iters_per_step: int = 6, verbose: bool = True):
        self.llm = LLM()
        self.registry: ToolRegistry = register_default_tools()
        self.max_iters_per_step = max_iters_per_step
        self.verbose = verbose

    def _log(self, *args) -> None:
        if self.verbose:
            print(*args)

    def plan(self, goal: str) -> Plan:
        plan = create_plan(self.llm, goal)
        self._log("\n📋 任务计划：")
        self._log(plan.render())
        return plan

    def execute(self, plan: Plan) -> list[str]:
        results: list[str] = []
        for step in plan.steps:
            self._log(f"\n▶ 执行第 {step.id} 步：{step.goal}")
            result = run_step(
                self.llm, self.registry,
                goal=plan.goal, step_id=step.id, step_goal=step.goal,
                history=results, max_iters=self.max_iters_per_step,
            )
            results.append(result)
            self._log(f"  ✅ 结论：{result[:120]}{'…' if len(result) > 120 else ''}")
        return results

    def summarize(self, plan: Plan, results: list[str]) -> str:
        self._log("\n📝 汇总生成最终方案…")
        numbered = "\n\n".join(
            f"### 步骤 {s.id}：{s.goal}\n{r}" for s, r in zip(plan.steps, results)
        )
        msg = self.llm.chat([
            {"role": "system", "content": SUMMARY_SYSTEM},
            {"role": "user", "content": SUMMARY_TEMPLATE.format(
                goal=plan.goal, plan=plan.render(), results=numbered)},
        ])
        return (msg.content or "").strip()

    def run(self, goal: str) -> str:
        plan = self.plan(goal)
        results = self.execute(plan)
        return self.summarize(plan, results)
