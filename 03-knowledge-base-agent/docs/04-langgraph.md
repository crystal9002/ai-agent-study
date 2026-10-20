# 04 · LangGraph 框架对照：手写循环 ↔ 状态图

代码：`scripts/04_langgraph.py`
（依赖：`uv pip install -p .venv/bin/python -r requirements-framework.txt`）

## 本课要点

- `create_agent` = 别人替你写好的 `KBAgent.run`，**同一套循环，两种写法**
- 它内部就是一张 `StateGraph`：`agent` 节点（LLM）⇄ `tools` 节点（ToolNode），条件边决定去留
- 框架会**并行执行同一批工具**——共享资源（本地模型）必须加锁，这是原生循环没有的坑

## 一、逐环节对照表

| 环节 | 原生版 | LangGraph 版 |
|------|--------|-------------|
| 工具注册 | `ToolRegistry` + `inspect` 手推 Schema | `@tool` / `tool(fn)` 装饰器（同一份函数） |
| 工具描述 | docstring 即 description | docstring 即 description（一样） |
| LLM 客户端 | `kba/llm.py` 手写 `OpenAI(...)` | `ChatOpenAI(model=…, base_url=…, api_key=…)` |
| ReAct 循环 | `agent.py` 手写 40 行（for + tool 回填） | `create_agent(llm, tools, system_prompt=SYSTEM)` |
| 消息历史管理 | 手工 `append` + `to_message()` | 图状态 `messages` 自动归并（add 通道） |
| 终止 | `if not msg.tool_calls` + `max_iters` | 条件边：有 tool_calls → tools 节点，否则 END |
| 事件回调 | `on_event` 自己发 | 节点粒度 hook / 流式 `astream_events`（本教程未用） |
| 检索层 | `kba/kb.py` | **完全复用**（`tool(search_kb)` 一行包装） |

## 二、手写循环 ↔ StateGraph 节点与边

`KBAgent.run` 的 `for` 循环，画成图就是：

```
                     ┌──────────────────────────────────────┐
START ──► agent 节点 │  LLM 决策：返回 tool_calls 还是答案？  │
          (llm.chat) └──────────────────────────────────────┘
                     有 tool_calls │                │ 没有
                                   ▼                ▼
                        tools 节点（ToolNode）      END（final）
                        执行 search_kb/calc/…
                        结果 append 进 messages
                                   │
                                   └──► 回到 agent 节点（条件边形成环）
```

- **状态**：原生版手工维护的 `messages` 列表，在图里是 `State` 的默认消息通道，
  节点返回增量、框架负责合并——这就是"状态即真相"。
- **条件边**：原生的 `if not msg.tool_calls: return`，变成
  `add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})`。
- **循环**：`tools → agent` 的普通边就是那个 `for`；`max_iters` 变成图的 `recursion_limit`
  （默认 25 步），超限由框架报 `GraphRecursionError`。

本教程刻意**不引入自定义 StateGraph**：单循环 ReAct 用预构建节点就够；
需要"计划 → 逐步执行 → 汇总"那种多节点编排，才手写 `StateGraph`（见 02 教程
`scripts/02_langgraph.py`，那才是节点/边的完整示范）。

## 三、对照版代码骨架

```python
tools = [tool(search_kb), tool(calc), tool(write_note), tool(list_notes)]
llm = ChatOpenAI(model=os.getenv("LLM_MODEL"),
                 base_url=os.getenv("OPENAI_BASE_URL"),
                 api_key=os.getenv("OPENAI_API_KEY"))
app = create_agent(llm, tools, system_prompt=SYSTEM)   # SYSTEM 与原生版一字不差
result = app.invoke({"messages": [("human", question)]})
```

**`system_prompt=SYSTEM` 复用原生的证据合同**——这正说明：prompt 合同与循环实现是
正交的两件事，换框架不用换合同。

> API 演进：早期写法是 `langgraph.prebuilt.create_react_agent(llm, tools, prompt=...)`，
> langgraph ≥ 1.0 起弃用，官方入口迁到 `langchain.agents.create_agent`（参数改名
> `prompt` → `system_prompt`，需额外装 `langchain>=1.0`）。本教程直接用新 API。
> 旧代码对照：`from langgraph.prebuilt import create_react_agent` + `prompt=SYSTEM` 仍能跑，
> 只是每次打印 `LangGraphDeprecatedSinceV10` 警告。

## 四、框架带来的新坑（本教程实际踩到）

1. **并行工具调用**：模型一次返回两个 `search_kb`（不同 query）时，ToolNode
   会并发执行 → 两个线程同时初始化 SentenceTransformer → 抛
   `Cannot copy out of meta tensor; no data!`。
   对策：`kba/kb.py` 用一把 `_LOCK`（RLock）把模型前向、索引懒加载串行化。
   **原生循环是 for 串行执行，天然没这个问题**——换框架时"并发语义"必须重新审。
2. **API 演进**：预构建 ReAct 的官方入口已从 `langgraph.prebuilt.create_react_agent`
   迁到 `langchain.agents.create_agent`（`prompt` 参数改名 `system_prompt`）。
   本教程脚本已用新 API；框架 API 的迁移节奏比手写循环快，这正是"合同与循环正交"
   的现实收益——换入口不动业务。
3. **安装顺序**：框架依赖装进同一个 `.venv`（`requirements-framework.txt`），
   两版脚本共享 `kba/` 与 `index/`，可直接 A/B 对比输出。

## 思考题

1. `create_agent` 的 `recursion_limit` 与原生 `max_iters=6`，语义完全等价吗？
2. 为什么把 `search_kb` 底层继续指向 `kba/kb.py`，而不是在 LangChain 里重写检索？
3. 想给框架版也接上 Web 的实时事件，你会选哪个机制？（提示：流式 API）

## 参考答案

1. 不完全等价：`max_iters` 数的是**循环轮数**，`recursion_limit` 数的是**图步数**
   （一轮 = agent + tools 两个节点）。换算关系约 `recursion_limit ≈ 2 × max_iters`，
   且超限表现为异常而非原生那句友好的中止文本——降级行为要自己包一层。
2. 检索质量（分块/召回/融合）与编排框架无关，是**可复用资产**；重写一遍等于两套
   实现两种 bug，且 A/B 对照失去意义。框架只该换"控制流"这层。
3. `app.astream_events(...)` 可以拿到节点粒度事件（`on_chain_start` /
   `on_tool_start` 等），映射成本教程的 `start/tool_call/tool_result/final`
   即可复用同一套前端；比原生的 `queue + on_event` 更标准，但要自己做事件名翻译。

## 上一课 / 下一课

上一课：[03 · Agent 循环](03-agent-loop.md) · 下一课：[05 · 生产化落地](05-production.md)
