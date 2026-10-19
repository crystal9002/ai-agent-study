# 05 LangGraph 对照：手写环节 ↔ 框架抽象

> 上一课：[04 手写多智能体](04-multi-agent.md) | 下一课：[06 生产化落地](06-production.md)
> 对应代码：`scripts/05_langgraph.py`（安装 `requirements-framework.txt` 后运行）

011 课说过："手写过一遍循环，是判断要不要用框架的前提。"现在前提已具备——
本篇把 `multi/` 的每个手写环节，映射到 LangGraph 的对应抽象，并跑同一个目标做对照。

## 1. 逐环节对应表

| 手写版（multi/） | LangGraph（scripts/05） | 说明 |
|---|---|---|
| `results/failures` 局部字典 | `StateGraph(GraphState)` 的 State | 框架托管状态，节点返回增量更新 dict 自动合并 |
| `Supervisor._route()` 的 LLM 路由 | `supervisor_node` 节点函数 | 提示词与 JSON 协议**原样复用** `SUPERVISOR_SYSTEM` |
| `if decision["action"]=="dispatch"` 分支 | `add_conditional_edges("supervisor", route_fn, …)` | 路由函数返回下一节点名；`"answer"` 映射到 END |
| `for round in range(max_rounds)` | supervisor ↔ worker 的**图回边** + `state["round"]` 计数 | 循环不再需要 for：worker 完成后沿回边再进 supervisor |
| `worker.run(task, llm)` | `make_worker_node(name)` 里的节点函数 | **直接复用** `multi.agents.WorkerAgent`——worker 本体无需框架化 |
| `max_rounds` / 重试上限 | `config={"recursion_limit": N}` | 框架级防死循环，与业务级上限双保险 |
| `runner.run()` 编排 | `app.invoke(state)` / `app.stream(...)` | invoke 拿最终 State；stream 逐节点拿中间态 |
| bus.on_event 事件流 | `stream_mode="updates"/"messages"` | 框架内建流式，不必自造事件协议（但自造的语义更贴业务） |
| （手写没有） | checkpointer（`MemorySaver` 等） | State 自动持久化，可断点恢复——手写要自己序列化 |

## 2. 图长什么样

```
        ┌─────────────────┐
entry──►│   supervisor    │◄──────────┐
        │ （路由 JSON）    │           │
        └───┬─────┬───┬───┘           │
  dispatch: │     │   │  dispatch:    │  dispatch:
            ▼     ▼   ▼               │  （回边）
     researcher calc writer ──────────┘
            │
            ▼ (action=answer)
           END
```

手写版里"for 循环的下一轮"，在这里是**边**；"分支选择"，在这里是**条件边**。
框架把控制流从"代码结构"提升成"显式数据结构"——这也是它能做可视化、checkpoint、
静态分析的原因。

## 3. 关键代码走读

**State**（手写字典 → TypedDict）：

```python
class GraphState(TypedDict, total=False):
    goal: str
    round: int
    results: dict[str, str]
    failures: dict[str, str]
    decision: dict
    final: str
```

**节点**（函数返回"增量更新"，框架负责合并进 State）：

```python
def make_worker_node(name):
    def node(state):
        result = workers[name].run(state["decision"]["task"], llm)  # 复用手写 worker
        results = dict(state.get("results") or {})
        results[name] = result
        return {"results": results}          # 只返回变化的键
    return node
```

**条件边**（手写 if-else → 声明式路由）：

```python
def route_after_supervisor(state):
    d = state.get("decision") or {}
    if d.get("action") == "dispatch" and d.get("worker") in workers:
        return d["worker"]        # → 节点名
    return "answer"               # → END

g.add_conditional_edges("supervisor", route_after_supervisor,
                        {**{n: n for n in workers}, "answer": "answer"})
for name in workers:
    g.add_edge(name, "supervisor")   # 回边：完成后再路由
```

注意 worker 本体（`WorkerAgent`）**一行没改**——框架化的是"编排层"，不是"执行层"。
这呼应 011 课的判断：单个 agent 的 ReAct 循环手写足够，复杂流程控制才需要图。

## 4. 实跑对照

```bash
.venv/bin/python scripts/05_langgraph.py
# 🧠 [round 1] supervisor → {'action':'dispatch','worker':'researcher',…}
# ✅ researcher 交回: 关键事实：1. 团队版单价 29 元/人/月…
# 🧠 [round 2] … calculator … 17,400 / 14,790 …
# 🧠 [round 3] … writer → output/summary.md
# 🧠 [round 4] {'action':'answer', …}
# 🏁 final: … 14,790 元/年 …
# 共经过 4 轮 supervisor 路由
```

与 `scripts/03` 手写版逐项对比：**同一目标、同一 worker、同一提示词协议，最终数字一致**；
差别只在控制流的表达位置（for 循环 vs 图回边）与状态的托管方（局部变量 vs State）。

## 5. 什么时候该从手写切到 LangGraph

看完对应表后，取舍其实很清晰：

**保持手写**（本教程 03/04 的形态）：
- 流程线性、轮数少（≤6）、团队就 1~2 人
- 需要精细控制每一轮的 token/延迟
- 深度定制消息格式（如 worker 的文本 JSON 协议）

**上 LangGraph**：
- 需要 checkpoint / 断点恢复（长任务中断续跑）
- 分支多、有并行扇出、有人机审批节点（interrupt + resume）
- 需要生态：LangSmith tracing、与 LangChain 生态工具/记忆组件互通
- 团队协作：图即文档，新人看 `add_edge` 就懂流程

## 思考题

1. 手写版的 `max_rounds=6` 和 LangGraph 的 `recursion_limit` 各自防什么？为什么建议两个都留？
2. 为什么 worker 节点里不直接返回最终答案，而要回边到 supervisor？
3. 如果要给流程加"人工审批：写文件前必须用户点确认"，两种实现各自怎么做？

### 参考答案

1. `max_rounds` 是**业务上限**：一轮 = 一次 supervisor 路由 + 一个 worker，6 轮已覆盖正常任务；它防的是"模型一直 dispatch 但没进展"的逻辑死循环。`recursion_limit` 是**框架保险丝**：每个节点执行都计数，防的是图结构本身接错（如回边写错导致无限节点执行）这类工程 bug。业务语义的上限用业务变量表达意图更清晰；框架保险丝兜住你没想到的情况——双保险才稳。
2. supervisor 是唯一的"全局决策者"：worker 交回的可能只是中间产物（如 calc 的三个数字），需要 supervisor 对照总目标判断"材料够了吗？下一步派谁？何时 answer？"。如果 worker 直接输出最终答案，就退化成了固定 pipeline，失去按结果动态调整的能力（比如检索结果不够时自动再派一次检索）。
3. 手写版：在 runner 里 writer 分发前加回调/状态检查，未确认则阻塞或发"待审批"事件。LangGraph：用 `interrupt`（或 human-in-the-loop node）在写文件节点前挂起，`checkpointer` 保存 State，用户确认后 `Command(resume=...)` 从断点继续——这正是框架价值最大的场景之一（断点恢复手写要自己序列化整个执行状态）。

---

*上一课：[04 手写多智能体](04-multi-agent.md) | 下一课：[06 生产化落地](06-production.md)*
