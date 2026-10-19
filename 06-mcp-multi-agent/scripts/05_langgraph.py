"""⑤ LangGraph 对照版：同一个 supervisor/worker 流程，框架怎么写。

手写版 ↔ LangGraph 逐环节对应（详见 docs/05-langgraph.md）：
  手写 supervisor._route 的 for 循环     →  StateGraph 的条件边（supervisor 节点后路由）
  手写 WorkerAgent.run                   →  worker 节点函数（内部仍调同一个 WorkerAgent）
  手写 results/failures 字典             →  State（框架托管、可 checkpoint）
  手写 max_rounds for 循环               →  图上 supervisor ↔ worker 的回边 + state.round 计数

运行：
  pip install -r requirements-framework.txt
  python scripts/05_langgraph.py
"""
import os
import sys
from pathlib import Path
from typing import Any, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from langgraph.graph import END, StateGraph

from llm import LLM
from multi.agents import WORKER_SYSTEM, WORKER_TOOLSET, WorkerAgent
from multi.supervisor import WORKERS_DESC, SUPERVISOR_SYSTEM

DEFAULT_GOAL = "查团队版定价，算 50 人一年的总费用（如有年付折扣请计入），写成 summary.md"
MAX_ROUNDS = 6


# ---------- State：手写版 results/failures 字典的框架化 ----------

class GraphState(TypedDict, total=False):
    goal: str
    round: int
    results: dict[str, str]      # worker → 结论
    failures: dict[str, str]     # worker → 最近失败原因
    decision: dict[str, Any]     # supervisor 最近一次决策
    final: str


def make_graph(llm: LLM):
    """构建 supervisor/worker 状态图。worker 复用手写版 WorkerAgent！"""
    # 静态 worker 实例（演示用；生产中可按需构造、并行执行）
    workers = {name: WorkerAgent(name, bus=_NullBus()) for name in WORKER_TOOLSET}

    def supervisor_node(state: GraphState) -> dict:
        """路由节点：与手写版 Supervisor._route 同一提示词、同一 JSON 协议。"""
        workers_text = "\n".join(f"- {k}: {v}" for k, v in WORKERS_DESC.items())
        user = (f"【总目标】{state['goal']}\n\n"
                f"【已完成的子任务结果】{state.get('results') or '（还没有）'}\n\n"
                f"【失败记录】{state.get('failures') or '（无）'}\n\n请决定下一步。")
        decision = llm.chat_json([
            {"role": "system",
             "content": SUPERVISOR_SYSTEM.format(workers=workers_text)},
            {"role": "user", "content": user},
        ])
        rnd = state.get("round", 0) + 1
        if decision.get("action") == "dispatch" and decision.get("worker") not in workers:
            decision = {"action": "answer", "content": f"（未知 worker {decision.get('worker')}）"}
        print(f"🧠 [round {rnd}] supervisor → {decision}")
        return {"decision": decision, "round": rnd}

    def route_after_supervisor(state: GraphState) -> str:
        """条件边：dispatch → 对应 worker 节点；answer → END。"""
        d = state.get("decision") or {}
        if d.get("action") == "dispatch" and d.get("worker") in workers:
            return d["worker"]
        return "answer"

    def make_worker_node(name: str):
        def node(state: GraphState) -> dict:
            task = (state.get("decision") or {}).get("task", "")
            result = workers[name].run(task, llm)   # 复用手写 WorkerAgent
            results = dict(state.get("results") or {})
            failures = dict(state.get("failures") or {})
            if result and not result.startswith("（失败") and '"error"' not in result[:200]:
                failures.pop(name, None)
            else:
                failures[name] = result[:200]
            results[name] = result
            print(f"✅ {name} 交回: {result[:120]}…")
            return {"results": results, "failures": failures}
        return node

    def answer_node(state: GraphState) -> dict:
        d = state.get("decision") or {}
        content = d.get("content") or "（无结论）"
        print(f"🏁 final: {content[:200]}")
        return {"final": content}

    # ---------- 组图：手写版的 for 循环在这里变成"回边" ----------
    g = StateGraph(GraphState)
    g.add_node("supervisor", supervisor_node)
    g.add_node("answer", answer_node)
    for name in workers:
        g.add_node(name, make_worker_node(name))

    g.set_entry_point("supervisor")
    g.add_conditional_edges("supervisor", route_after_supervisor,
                            {**{n: n for n in workers}, "answer": "answer"})
    for name in workers:
        g.add_edge(name, "supervisor")      # worker 完成 → 回到 supervisor 再路由
    g.add_edge("answer", END)
    return g.compile()


class _NullBus:
    """框架版演示中不接总线时的空实现（生产里可换成真实 EventBus）。"""
    def send(self, *a, **kw): pass
    def emit(self, *a, **kw): pass


def main() -> None:
    goal = sys.argv[1].strip() if len(sys.argv) > 1 else DEFAULT_GOAL
    print(f"🎯 目标: {goal}\n")
    print("── LangGraph StateGraph 执行轨迹 ──")
    try:
        llm = LLM()
        app = make_graph(llm)
        state: dict = {"goal": goal, "round": 0, "results": {}, "failures": {}}
        # invoke 跑完整张图（节点内已打印轨迹）；生产可改 app.stream(..., stream_mode="updates")
        result_state: GraphState = app.invoke(state, config={"recursion_limit": 30})
    except ImportError as e:
        print(f"❌ 缺少框架依赖: {e}\n   请先: pip install -r requirements-framework.txt")
        return
    except Exception as e:  # noqa: BLE001
        print(f"❌ 运行失败: {type(e).__name__}: {e}")
        print("   排查：确认 .env 的 OPENAI_BASE_URL/API_KEY 可用；网络问题重试一次")
        return

    print("\n── 与手写版（scripts/03）对照 ──")
    print("  手写版 results/failures 局部字典  ==  LangGraph 的 State（框架托管、可持久化）")
    print(f"  共经过 {result_state.get('round')} 轮 supervisor 路由")
    print(f"  有结果的 worker: {list((result_state.get('results') or {}).keys())}")
    print("\n🏁 最终结论:")
    print(result_state.get("final") or "（图未走到 answer 节点，请检查日志）")


if __name__ == "__main__":
    main()
