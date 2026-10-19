# 03 · 原生 Agent 循环：单循环 ReAct 逐行讲解

代码：`kba/agent.py`、`kba/llm.py`（对照 02 教程 `agent/executor.py`）

## 本课要点

- 循环的**终止权在模型手里**（不再返回 `tool_calls` 即结束），所以必须设 `max_iters`
- 消息历史是唯一记忆：`assistant(tool_calls)` → `tool(结果)` 成对回填
- 与 02 教程的差异：这里是**一竿子到底的单循环 ReAct**，不是 Plan-and-Execute 的步内执行器

## 一、循环骨架（`KBAgent.run`，40 行核心）

```python
messages = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": question}]
for _ in range(self.max_iters):                 # ① 轮数上限：跑飞最后防线
    msg = self.llm.chat(messages, tools=self.registry.specs())   # ② 带工具规格调 LLM
    messages.append(LLM.to_message(msg))        # ③ assistant 消息进历史（含 tool_calls）

    if not msg.tool_calls:                      # ④ 模型说"我答完了" → 正常终止
        emit({"type": "final", "content": answer})
        return answer

    for tc in msg.tool_calls:                   # ⑤ Act：宿主执行工具
        emit({"type": "tool_call", ...})
        result = self.registry.invoke(tc.function.name, tc.function.arguments)
        emit({"type": "tool_result", ...})
        messages.append({"role": "tool", "tool_call_id": tc.id,   # ⑥ Observe：结果回填
                         "content": json.dumps(result, ensure_ascii=False)})
# ⑦ 走到这里 = 超过 max_iters：返回中止说明，而不是死循环
```

一次典型执行的**实际事件序列**（`scripts/02_kb_agent.py` 输出）：

```
start → tool_call(search_kb) → tool_result(5 条命中, 带 n)
      → tool_call(calc 25*12*0.8*50) → tool_result 12000
      → tool_call(calc 25*12*50) → tool_result 15000
      → final（带 [2][3][4][5] 引用与来源清单）
```

三重终止保险：**模型主动停**（正常路径）→ **`max_iters=6`**（单轮循环）→
**工具侧不抛异常**（错误回填，模型换参数自救，而不是卡在异常上）。

## 二、与 02 敥程 executor 的关键差异

| | 02 教程 `executor.run_step` | 本教程 `KBAgent.run` |
|---|---|---|
| 循环的**单位** | 一个**规划步骤**（外层还有 for 步骤循环） | **整个问题**（没有外层编排） |
| 解决的问题 | "这一步怎么干"（Plan-and-Execute 的执行器） | "这个问题怎么答"（单循环 ReAct） |
| system prompt | 步骤上下文：总目标 + 已完成步骤 + 当前步骤 | 证据合同：先检索、带引用、查不到明说 |
| 输出 | 步骤结论文本，交给汇总节点 | 用户最终回答 |
| 上下文增长 | 每步**新建 messages**（history 摘要传话） | **一条历史一直长**（工具结果全量累积） |
| 典型代价 | 步间靠人工摘要传递，可控 | 长任务上下文膨胀 → 靠 `max_iters` 与工具返回截断压住 |

一句话：**02 的循环是"更大机器里的一个齿轮"，本教程的循环就是整台机器**。
什么时候需要外层规划？当任务能拆成各自独立、需要不同上下文的多步（差旅规划）；
当任务是"围绕一个事实问题的短链推理"（查价 + 算账），单循环更简单也更稳。

## 三、工程细节（生产必读）

1. **`LLM.to_message` 必须保留 `tool_calls`**：回传时丢掉它，API 会报
   "tool_calls 与 tool 消息不配对"。
2. **`on_event` 回调**：`run()` 同步阻塞，Web 版在工作线程里把事件塞
   `queue.Queue`，SSE 生成器边取边发（`scripts/03_web.py`）——与 02 教程同一姿势。
3. **每轮完整历史都带上**：模型能"看见"自己查过什么，避免重复检索同一个问题。
4. **成本估算**：`max_iters=6` ⇒ 最坏 6 次 LLM 调用 + 6 次工具调用；
   实际知识库问答 2~3 轮收敛。

## 代码对应

| 环节 | 位置 |
|------|------|
| 循环与终止 | `kba/agent.py::KBAgent.run` |
| 证据合同 | `kba/agent.py::SYSTEM` |
| LLM 调用与消息回传 | `kba/llm.py::chat` / `to_message` |
| 事件（Web 复用） | `on_event` 回调；消费方 `scripts/02_kb_agent.py`、`scripts/03_web.py` |
| 对照：Plan-and-Execute | 02 教程 `agent/task_agent.py` + `agent/executor.py` |

## 思考题

1. 为什么 `max_iters` 到期时返回的是**一句中止说明文本**，而不是抛异常或空字符串？
2. 循环里 `messages` 会一直增长，哪一类内容最该先截断？为什么不是 system prompt？
3. 什么信号说明这个任务**该换回** 02 教程的 Plan-and-Execute 结构？

## 参考答案

1. 返回文本是**可交付的降级结果**：CLI 直接打印、Web 作为 final 事件推给前端，
   用户看到的是"没答完 + 原因"，而不是一个红色堆栈。抛异常会打断 `on_event` 流，
   空字符串会让上游无法区分"失败"和"模型没说话"。
2. **工具返回（tool 消息）**最该截断：单条 `search_kb` 结果可到几千字，多轮累积
   最快。system prompt 是每轮都要精确遵循的合同，截了反而破坏行为；本教程靠
   chunk 分块（~400 字）天然限长，生产上还要对 tool 结果做摘要或滚动窗口。
3. 出现**步骤间上下文差异大、需要独立收敛**的信号时：比如"先调研 5 家供应商 →
   再比价 → 再写报告"，每步需要的资料和输出格式都不同，塞进一个循环会让上下文
   又长又杂（02 教程 docs/03 的取舍表讲了同一件事）。

## 上一课 / 下一课

上一课：[02 · 检索即工具](02-search-as-tool.md) · 下一课：[04 · LangGraph 对照](04-langgraph.md)
