"""框架版：LangGraph 实现同样的 任务规划型 Agent（生产写法）。

对应原生版逐环节：
  planner.py    → plan_node（with_structured_output 结构化规划）
  executor.py   → step_node（create_react_agent 子循环）
  task_agent.py → StateGraph 状态图编排（状态机替代手写 for 循环）

用法：
    pip install -r requirements-framework.txt
    python scripts/02_langgraph.py "下周二到周四去上海出差，帮我安排行程"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
from typing import TypedDict

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel, Field

from agent.tools import (add_calendar_event, calc, get_calendar, get_weather,
                         save_itinerary, search_flights, search_hotels)

DEFAULT_GOAL = "下周二到周四去上海出差（从北京出发），帮我安排完整的差旅行程"


# ---------- 1. 工具：同一份业务函数，套上 LangChain @tool ----------
tools = [
    tool(search_flights), tool(search_hotels), tool(get_weather),
    tool(get_calendar), tool(add_calendar_event), tool(calc), tool(save_itinerary),
]

llm = ChatOpenAI(
    model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
    base_url=os.getenv("OPENAI_BASE_URL"),
    api_key=os.getenv("OPENAI_API_KEY"),
    temperature=0.2,
)


# ---------- 2. 结构化规划（替代 planner.py 的手工 JSON 解析） ----------
class Step(BaseModel):
    id: int
    goal: str = Field(description="可独立执行的具体步骤")
    tools: list[str] = Field(default_factory=list, description="候选工具名")


class Plan(BaseModel):
    steps: list[Step]


class State(TypedDict):
    """图的全局状态——原生版里在函数间手工传递的 plan/results/游标，这里声明在一处。"""
    goal: str
    plan: list[dict]
    current: int          # 当前执行到第几步
    results: list[str]
    answer: str


def plan_node(state: State) -> dict:
    planner = llm.with_structured_output(Plan)
    plan = planner.invoke([
        ("system", "你是任务规划助手。把目标分解为 3~6 个有序、可独立执行的步骤。"),
        ("user", f"任务目标：{state['goal']}"),
    ])
    for s in plan.steps:
        print(f"  {s.id}. {s.goal}")
    return {"plan": [s.model_dump() for s in plan.steps], "current": 0, "results": []}


def step_node(state: State) -> dict:
    """执行一步：LangGraph 预构建的 ReAct Agent 就是原生版 executor.run_step。"""
    step = state["plan"][state["current"]]
    history = "\n".join(f"- {r[:300]}" for r in state["results"]) or "（暂无）"
    print(f"\n▶ 执行第 {step['id']} 步：{step['goal']}")

    agent = create_react_agent(llm, tools)
    out = agent.invoke({"messages": [
        ("system", "完成【当前步骤】后输出简明结论（含关键数据），全程中文。"
                   "工具报错要换参数重试；不要输出过程性描述。"),
        ("user", f"总目标：{state['goal']}\n\n已完成步骤：\n{history}\n\n"
                 f"当前步骤（第 {step['id']} 步）：{step['goal']}"),
    ]})
    answer = out["messages"][-1].content
    print(f"  ✅ {answer[:120]}")
    return {"results": state["results"] + [answer],
            "current": state["current"] + 1}


def route(state: State) -> str:
    """条件边：还有步骤 → 继续执行；全部完成 → 汇总。"""
    return "step" if state["current"] < len(state["plan"]) else "summarize"


def summarize_node(state: State) -> dict:
    numbered = "\n\n".join(
        f"### 步骤 {s['id']}：{s['goal']}\n{r}"
        for s, r in zip(state["plan"], state["results"])
    )
    msg = llm.invoke([
        ("system", "你是差旅规划专家。根据目标与步骤结果输出完整 Markdown 行程方案，"
                   "含：行程概览/交通/住宿/天气提醒/日程表/费用预估/风险与建议。"
                   "只用真实数据并标注来源步骤，执行失败的部分如实说明。"),
        ("user", f"任务目标：{state['goal']}\n\n各步骤结果：\n{numbered}"),
    ])
    return {"answer": msg.content}


# ---------- 3. 组图：START → plan → (step ⇄) → summarize → END ----------
def build_graph():
    g = StateGraph(State)
    g.add_node("plan", plan_node)
    g.add_node("step", step_node)
    g.add_node("summarize", summarize_node)
    g.add_edge(START, "plan")
    g.add_conditional_edges("plan", route, {"step": "step", "summarize": "summarize"})
    g.add_conditional_edges("step", route, {"step": "step", "summarize": "summarize"})
    g.add_edge("summarize", END)
    return g.compile()


def main() -> None:
    goal = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GOAL
    print(f"🎯 目标: {goal}\n" + "=" * 60)
    try:
        final = build_graph().invoke({"goal": goal})
    except Exception as e:
        print(f"❌ 运行失败: {type(e).__name__}: {e}")
        print("请先 pip install -r requirements-framework.txt，并检查 .env 配置")
        return

    print("\n" + "=" * 60)
    print("📄 最终方案:\n")
    print(final["answer"])
    out = Path(__file__).parent.parent / "output" / "itinerary_langgraph.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(final["answer"], encoding="utf-8")
    print(f"\n💾 已保存: {out}")


if __name__ == "__main__":
    main()
