"""编排入口：run(goal, on_event) → 事件流 + 最终结论。

事件协议（CLI / Web SSE 共用同一套 type）：
  supervisor_plan  每轮路由决策（dispatch → 谁 / answer 收尾）
  dispatch         具体分派（from supervisor to worker，含任务文本）
  worker_step      worker 内一次工具调用（tool/args/result）
  worker_done      worker 交回结果
  worker_retry     验收失败重派
  worker_failed    重派后仍失败，放弃
  final            最终结论
  error            运行期异常（也会作为事件流出去，不炸进程）

用法（CLI）：
    from multi.runner import run
    final = run("查团队版定价，算50人年费", on_event=print)
用法（Web）：on_event 塞进 queue.Queue，SSE 生成器边取边发（见 scripts/04_web.py）。
"""
from __future__ import annotations

import traceback
from typing import Callable

from llm import LLM
from multi.agents import make_workers
from multi.bus import EventBus, Message
from multi.supervisor import Supervisor

EventCB = Callable[[dict], None] | None


def run(goal: str, on_event: EventCB = None, verbose: bool = True) -> str:
    """跑一次多智能体协作，返回最终结论文本。"""

    def emit(type_: str, **kw) -> None:
        event = {"type": type_, **kw}
        if on_event:
            on_event(event)
        if verbose:
            _print_event(event)

    bus = EventBus()

    # 总线消息 → 结构化事件：supervisor 派活给 worker 时补一条 dispatch 事件
    def bus_to_event(msg: dict) -> None:
        if msg["from"] == "supervisor" and msg["to"] in ("researcher", "calculator", "writer"):
            emit("dispatch", to=msg["to"], task=msg["content"])
        elif msg["from"] == "user":
            emit("goal", goal=msg["content"])
    bus.subscribe(bus_to_event)

    # worker 内每次工具调用 → worker_step 事件（可观察性核心）
    def on_tool(ev: dict) -> None:
        emit("worker_step", worker=ev["worker"], tool=ev["tool"],
             args=ev["args"], result=ev["result"])

    workers = make_workers(bus, on_tool=on_tool)

    try:
        llm = LLM()
        # supervisor 的 supervisor_plan/worker_done/final 事件：有 on_event 就推，
        # 没有就打印（CLI 模式）；两者都有时先推再打，保证事件完整可观察
        def sup_event(e: dict) -> None:
            if on_event:
                on_event(e)
            if verbose:
                _print_event(e)

        supervisor = Supervisor(llm, workers, bus, on_event=sup_event)
        final = supervisor.run(goal)
        emit("final", content=final)
        return final
    except Exception as e:  # noqa: BLE001
        emit("error", message=f"{type(e).__name__}: {e}",
             trace=traceback.format_exc(limit=3))
        return f"运行失败: {type(e).__name__}: {e}"


_ICONS = {
    "goal": "🎯", "supervisor_plan": "🧠", "dispatch": "📤",
    "worker_step": "🔧", "worker_done": "✅", "worker_retry": "🔁",
    "worker_failed": "❌", "final": "🏁", "error": "💥",
}


def _print_event(event: dict) -> None:
    t = event.get("type", "?")
    icon = _ICONS.get(t, "·")
    if t == "goal":
        print(f"{icon} 目标: {event['goal']}")
    elif t == "supervisor_plan":
        print(f"{icon} [round {event.get('round')}] {event.get('decision')}"
              f"  task={str(event.get('task'))[:80]}…")
    elif t == "dispatch":
        print(f"{icon} supervisor → {event['to']}: {str(event['task'])[:100]}")
    elif t == "worker_step":
        print(f"{icon} {event['worker']} 调用 {event['tool']}({event['args']}) "
              f"→ {str(event['result'])[:120]}")
    elif t == "worker_done":
        tag = "（重派）" if event.get("retried") else ""
        print(f"{icon} {event['worker']} 交回{tag}: {str(event['result'])[:150]}")
    elif t == "worker_retry":
        print(f"{icon} {event['worker']} 验收失败，重派。原因: {event['reason'][:100]}")
    elif t == "worker_failed":
        print(f"{icon} {event['worker']} 放弃: {event['reason']}")
    elif t == "final":
        print(f"{icon} 最终结论:\n{event['content']}")
    elif t == "error":
        print(f"{icon} {event['message']}")
