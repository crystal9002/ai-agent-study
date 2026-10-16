# 03 · 规划与执行：把长任务拆成可控的步骤

代码：`agent/planner.py`、`agent/executor.py`、`agent/task_agent.py`

## 规划（planner.py）

`create_plan()` 用一个 LLM 调用把目标变成结构化计划：

```json
{"steps": [
  {"id": 1, "goal": "查询 10-20 北京→上海航班，选 3 个候选", "tools": ["search_flights"]},
  {"id": 2, "goal": "查询 10-20 至 10-22 上海酒店", "tools": ["search_hotels"]}, …
]}
```

工程细节（LLM 结构化输出的通用套路）：

- System Prompt 规定**格式 + 数量约束（3~6 步）+ 每步可独立执行**
- `_extract_json()` 取首个 `{` 到末个 `}`，容忍代码块围栏与前后废话
- 解析后落成 `Step` dataclass，下游不碰原始 dict；空计划直接报错

> 生产可用 `response_format={"type":"json_object"}` 或框架的 `with_structured_output()` 强约束，比纯提示词更稳（LangGraph 版已演示）。

## 执行（executor.py）——每步一个 ReAct 循环

```python
for _ in range(max_iters):          # ① 硬上限，防失控
    msg = llm.chat(messages, tools=registry.specs())
    messages.append(to_message(msg))
    if not msg.tool_calls:
        return msg.content          # ② 模型宣布本步完成
    for tc in msg.tool_calls:       # ③ Act + Observe
        result = registry.invoke(tc.function.name, tc.function.arguments)
        messages.append({"role": "tool", "tool_call_id": tc.id, "content": json(result)})
```

三个关键上下文设计：

1. **Step System Prompt**：告诉执行者"你在完成计划的某一步"，并规定完成标准（基于真实数据、错误要重试、输出结论而非过程描述）。
2. **History 注入**：前面步骤的结论（截断到各 800 字）带进本步上下文——这是步骤间唯一的传话机制，让"订酒店"能知道"航班几点到"。
3. **每步独立 messages**：不复用全局大对话。长任务的上下文是靠**结构化传递**（history 摘要），不是靠把所有聊天记录塞进去。

## 编排与失败处理（task_agent.py）

```python
plan = self.plan(goal)                # 规划失败 → 报错终止（fail fast）
results = []                          # 逐步执行，结果累积
for step in plan.steps:
    result = run_step(...)            # 单步失败 → 作为文本记录，不中断整体
    results.append(result)
final = self.summarize(plan, results) # 汇总时如实说明失败部分
```

- **步内失败不等于任务失败**：`run_step` 超限时返回失败标记，后续步骤仍继续，汇总阶段由 LLM 如实披露——比整轮崩溃的体验好得多。
- **终止条件三重保险**：模型主动停（正常）→ `max_iters`（步内）→ 步骤遍历完（全局）。
- **可观测性**：每步打印工具调用与结论（`🔧 search_flights(…) →`、`✅ 结论：…`），规划型 Agent 的调试主要靠看这条时间线。

## 进阶：失败重规划（RePlan）

更完整的模式在执行中途发现计划不可行时回头改计划：步骤失败率超阈值 → 把目标+已有结果+失败原因再喂给规划器 → 生成补救步骤。本教程作为练习留白，实现位置在 `TaskAgent.execute()` 的失败分支里。

## 下一步

[04 · LangGraph 框架写法](04-langgraph.md)
