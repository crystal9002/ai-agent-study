# 04 · LangGraph 框架写法

代码：`scripts/02_langgraph.py`
（依赖：`pip install -r requirements-framework.txt`）

LangGraph 是 LangChain 团队推出的**状态机编排框架**，Agent 生产落地的主流选择：
把 Agent 表达成"带共享状态的图"，节点是计算、边是控制流，支持断点续跑与人工介入。

## 与原生版逐环节对照

| 环节 | 原生版 | LangGraph 版 |
|------|--------|-------------|
| 工具 | `ToolRegistry` + 手推 Schema | `tool(search_flights)` 一行包装 |
| LLM | `llm.py` 手写客户端 | `ChatOpenAI(base_url=…)` |
| 规划 | 手写 JSON 提示词 + 解析 | `llm.with_structured_output(Plan)` + Pydantic |
| ReAct 循环 | `executor.py` 手写 40 行 | `create_react_agent(llm, tools)` 预构建 |
| 编排 | `task_agent.py` 手写 for | `StateGraph` 节点 + 条件边 |
| 状态传递 | 手工管理 `history` 列表 | 声明式 `State(TypedDict)`，节点返回增量更新 |

## 核心概念：状态图

```python
class State(TypedDict):     # 全局状态——原生版散落在参数里的东西，这里声明在一处
    goal: str
    plan: list[dict]
    current: int            # 游标：执行到第几步
    results: list[str]
    answer: str
```

```python
g = StateGraph(State)
g.add_node("plan", plan_node)        # 节点 = 纯函数：读 State → 返回要更新的字段
g.add_node("step", step_node)
g.add_node("summarize", summarize_node)
g.add_edge(START, "plan")
g.add_conditional_edges("plan", route, ...)   # 条件边：还有步骤→step，否则→summarize
g.add_conditional_edges("step", route, ...)   # step 节点自己形成环 → 多步循环
g.add_edge("summarize", END)
app = g.compile()
```

**`route()` 函数实现循环**：这是与原生 `for step in plan.steps` 完全等价的控制流——
区别只是循环条件从"写死的 for"变成"图上的条件边"，换来的是：整条执行路径**可绘制、可持久化、可在任意节点暂停**。

## 三个"白嫖"到的能力

1. **结构化规划**：`with_structured_output(Plan)` 直接返回 Pydantic 模型，解析健壮性由框架兜底。
2. **预构建 ReAct**：`create_react_agent` 内置了 executor.py 手写的工具循环 + 错误处理。
3. **状态即真相**：`final = app.invoke({"goal": …})` 拿到完整中间状态，天然可存档（配 Checkpointer 可从任意断点恢复）——手写版要把 results 刻意返回出来。

## 怎么选

- **直接用 LangGraph 起步**：大多数生产场景的正确答案（本教程推荐的默认姿势）。
- **原生版的价值**：框架黑盒里的每一步你都能用原生版复述出来；排障、定制循环终止策略、评估指标埋点时这个能力决定上限。
- 跑一遍 `scripts/01_task_agent.py` 再跑 `02_langgraph.py`，对比两者的计划与输出。

## 下一步

[05 · 生产化落地](05-production.md)
