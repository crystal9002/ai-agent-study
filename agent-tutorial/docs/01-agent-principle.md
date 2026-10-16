# 01 · Agent 原理：规划型 Agent 是怎么跑起来的

## Agent = LLM + 工具 + 循环

| 形态 | 区别 |
|------|------|
| 普通 LLM 对话 | 单轮生成，模型不动手 |
| RAG | 检索是**固定链路**：embed → search → generate，没有决策 |
| Workflow | 流程由人预先写死（DAG），模型只做节点内任务 |
| **Agent** | **模型自己决定**下一步做什么：调哪个工具、调几次、何时结束 |

判定标准：控制流是否由 LLM 在运行时决定。是 → Agent；否则是 Workflow。

## 两种核心范式

### ① ReAct（单步内怎么干）

```
Thought: 我需要先查航班 → Action: search_flights(...) → Observation: [{...}]
Thought: 拿到了，再查天气 → Action: get_weather(...) → Observation: {...}
Thought: 信息齐了 → Final Answer: 结论…
```

生产实现不解析文本格式，而是用 **Function Calling**：模型返回结构化的 `tool_calls`，宿主程序执行后以 `tool` 角色回填结果，循环直到模型不再要求调工具。对应本项目 `agent/executor.py::run_step()`，要点：

- 循环由模型自主终止，**必须设 `max_iters` 上限**防跑飞
- 工具错误转成结构化错误回填（`registry.invoke` 不抛异常），让模型有机会自我纠错
- 每轮完整对话历史都带上，模型能"看见"自己此前调过什么

### ② Plan-and-Execute（多个任务怎么排）——本教程场景

任务"安排一次差旅"包含多个耦合的子目标（航班→酒店→天气→日程）。两种策略：

| | ReAct 一竿子到底 | Plan-and-Execute（本项目） |
|---|---|---|
| 过程 | 一个大循环里自由发挥 | 先规划出步骤，再逐步执行 |
| 优点 | 简单 | **计划可见可审、每步上下文小而准、失败可定位到步骤** |
| 缺点 | 长任务易失焦、过程黑盒 | 计划可能需要中途调整 |

本项目链路（`agent/task_agent.py`）：

```
目标
 │ ① 规划 planner.py → Plan[{id, goal, tools}]（JSON 结构化输出）
 ▼
逐步执行 executor.py → 每步一个 ReAct 循环，结果累积进 history
 │ ② 前面步骤的结果作为后面步骤的上下文（查完航班再订酒店）
 ▼
汇总 task_agent.py::summarize → 整合出最终 Markdown 方案
```

## 三种写法的对照（本教程目录）

| 环节 | 原生版 | LangGraph 版 |
|------|--------|-------------|
| 工具注册 | `tools.py` 手写注册表（签名→JSON Schema） | `@tool` 装饰器 |
| 规划 | `planner.py` 手写 JSON 解析 | `with_structured_output(Plan)` + Pydantic |
| ReAct 循环 | `executor.py` 手写 while + tool 回填 | `create_react_agent` 预构建节点 |
| 编排 | `task_agent.py` 手写 for 循环 | `StateGraph` 状态图 + 条件边 |

先跑通原生版（[02](02-tools.md) → [03](03-planning.md)），再看框架版 [04](04-langgraph.md)。

## 下一步

[02 · 工具与 Function Calling](02-tools.md)
