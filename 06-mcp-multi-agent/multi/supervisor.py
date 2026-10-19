"""Supervisor：多智能体的"大脑"——路由、分发、验收、汇总。

职责（对应 006 课 Supervisor 模式）：
  1. 路由：看目标 + 已有结果 → 决定下一步（dispatch 给某个 worker / answer 直接收尾）
  2. 分发：把子任务文本发给 worker（worker 看不到全局，只见任务文本）
  3. 验收：worker 返回结果后判断是否够用；不合格/失败带意见重派一次
  4. 汇总：所有材料齐了 → 生成最终回答

协议：supervisor 的 LLM 输出结构化 JSON：
  {"action": "dispatch", "worker": "researcher|calculator|writer", "task": "..."}
  {"action": "answer", "content": "最终结论"}

失败处理：worker 报错或明显空结果 → 重派一次（附失败原因）；再失败则跳过并记录。
"""
from __future__ import annotations

import json
from typing import Callable

from llm import LLM
from multi.agents import WorkerAgent
from multi.bus import EventBus

WORKERS_DESC = {
    "researcher": "检索专家：查产品知识库（定价/功能/折扣 FAQ）。适合'查/找/问价格'类任务。",
    "calculator": "计算专家：做算术（单价×人数×月数等）。适合'算/总计/多少元'类任务。",
    "writer": "写作专家：把素材写成 output/ 下的 Markdown 文件。适合'写/整理成文档'类任务。",
}

SUPERVISOR_SYSTEM = """你是多智能体系统的调度员（supervisor）。手下有三名 worker：
{workers}

每一轮你只能做一件事，输出一个 JSON：
- 派活：{{"action":"dispatch","worker":"<worker 名>","task":"<给该 worker 的完整任务文本，自包含，不依赖上下文>"}}
- 收尾：{{"action":"answer","content":"<基于已有结果的最终结论>"}}

规则：
1. 任务文本必须自包含：worker 看不到之前的对话，需要的数字/口径都要写进 task。
2. 已有结果够回答目标时才 answer；answer 引用的数字必须来自 worker 结果。
3. 失败的 worker 会带着失败原因回来，重派时把原因写进 task。
4. 不确定派给谁时：查资料→researcher，算数→calculator，写文件→writer。
"""

# 结构化验收：结果里带 error、或长度过短，视为不合格
def _result_ok(content: str) -> bool:
    if not content or content.strip().startswith("（失败"):
        return False
    if '"error"' in content[:200]:
        return False
    return len(content.strip()) >= 8


class Supervisor:
    def __init__(self, llm: LLM, workers: dict[str, WorkerAgent], bus: EventBus,
                 max_rounds: int = 6, on_event: Callable[[dict], None] | None = None):
        self.llm = llm
        self.workers = workers
        self.bus = bus
        self.max_rounds = max_rounds
        self.on_event = on_event

    def _emit(self, type_: str, **kw) -> None:
        """结构化事件（区别于总线的 Message：给 SSE/CLI 可视化用）。"""
        event = {"type": type_, **kw}
        if self.on_event:
            self.on_event(event)

    def _route(self, goal: str, results: dict, failures: dict) -> dict:
        """LLM 路由：输出 {action, worker?, task?, content?}。"""
        workers_text = "\n".join(f"- {k}: {v}" for k, v in WORKERS_DESC.items())
        done_text = json.dumps(results, ensure_ascii=False, indent=1) or "（还没有）"
        fail_text = json.dumps(failures, ensure_ascii=False) or "（无）"
        user = (f"【总目标】{goal}\n\n【已完成的子任务结果】{done_text}\n\n"
                f"【失败记录（重派时把原因写进 task）】{fail_text}\n\n"
                "请决定下一步。")
        decision = self.llm.chat_json([
            {"role": "system", "content": SUPERVISOR_SYSTEM.format(workers=workers_text)},
            {"role": "user", "content": user},
        ])
        # 校验 worker 名，防 LLM 幻觉出不存在的 worker
        if decision.get("action") == "dispatch" and decision.get("worker") not in self.workers:
            decision = {"action": "answer",
                        "content": f"（路由失败：未知 worker {decision.get('worker')}，"
                                   f"已有结果：{json.dumps(results, ensure_ascii=False)}）"}
        return decision

    def run(self, goal: str) -> str:
        self.bus.send("user", "supervisor", goal)
        results: dict[str, str] = {}    # worker → 最终结论文本
        failures: dict[str, str] = {}   # worker → 最近一次失败原因（重派用）
        retries: dict[str, int] = {}    # worker → 已重派次数

        for round_no in range(1, self.max_rounds + 1):
            decision = self._route(goal, results, failures)
            action = decision.get("action")

            if action != "dispatch":
                content = decision.get("content") or "（supervisor 未给出结论）"
                self._emit("supervisor_final", content=content, rounds=round_no)
                self.bus.send("supervisor", "user", content)
                return content

            worker_name = decision["worker"]
            task = decision.get("task") or ""
            self._emit("supervisor_plan", round=round_no,
                       decision=f"dispatch → {worker_name}", task=task)
            self.bus.send("supervisor", worker_name, f"[round {round_no}] {task}")

            worker = self.workers[worker_name]
            result = worker.run(task, self.llm)
            results[worker_name] = result
            self._emit("worker_done", worker=worker_name, result=result)

            if _result_ok(result):
                failures.pop(worker_name, None)
                continue

            # 验收失败 → 重派一次（附原因）；再失败就记录、不再纠缠
            retries[worker_name] = retries.get(worker_name, 0) + 1
            if retries[worker_name] > 1:
                failures[worker_name] = "重派后仍失败，放弃该子任务"
                self._emit("worker_failed", worker=worker_name,
                           reason="重派后仍失败，放弃")
                continue
            reason = result[:200] if result else "（空结果）"
            failures[worker_name] = reason
            self._emit("worker_retry", worker=worker_name, reason=reason)
            retry_task = (f"{task}\n\n【注意：上一次执行失败：{reason}，"
                          "请换一种方式完成。】")
            result2 = worker.run(retry_task, self.llm)
            results[worker_name] = result2
            self._emit("worker_done", worker=worker_name, result=result2, retried=True)

        # 轮数耗尽：强制收尾，不无限循环
        fallback = "（达到最大轮数，强制汇总）已有结果：" + json.dumps(
            results, ensure_ascii=False)
        self._emit("supervisor_final", content=fallback, rounds=self.max_rounds)
        return fallback
