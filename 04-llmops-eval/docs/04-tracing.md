# 04 · Tracing：Span 树与成本归因

代码：`llmops/trace.py`、`scripts/01_trace_demo.py`、`llmops/store.py`

## 从 009 课的一行日志到一棵 Span 树

理论课 [009 · 评估与观测](../../AI-Agent开发教程/009-评估与观测.md) 里说过：一次 Agent 运行 = 一条 trace，内部是多个 span，必须记 token/成本/失败原因。本课把这行概念落成可运行的 `llmops/trace.py`。

三个概念：

- **Trace**：一次完整运行，`run_id` 唯一（`20261019-020152-1ff021` 这种"时间戳+随机后缀"）。
- **Span**：一个有名字的环节（`retrieve` / `generate` / `judge:faithfulness` / `tool:search`），记录输入、输出、token、延迟、错误、成本。
- **父子关系**：`parent_id` 把 span 串成树。`01_trace_demo.py` 跑一次的树长这样：

```
═══ Trace 20261019-020152 · trace_demo ═══
├─ retrieve  0ms
│    入参: 智能云盘团队版的价格是多少？
├─ generate  1417ms 180+24tok $0.0001
│    出参: 智能云盘团队版为每位成员每月 29 元…
├─ judge:faithfulness  593ms 270+25tok
└─ judge:relevance     638ms 155+28tok
```

没有树，你只有一堆平铺日志，分不清"这 1417ms 里生成占多少、judge 占多少"；有了树，成本和延迟都能归因到环节。

## 两种打点姿势（`trace.py`）

**装饰器**——给函数无侵入包一层，自动记 latency / error / 父子：

```python
@tr.record_span("retrieve")
def retrieve_spanned(q: str, k: int = 3):
    return retrieve(q, k=k)
```

**with 上下文**——需要分段记 output、或逻辑不适合整函数包裹时用：

```python
with tr.span("generate", inputs=question) as sp:
    answer = generate(question, chunks, trace=tr)
    sp.output = answer
```

底层是同一个 `span()` contextmanager：进栈记 `parent_id`（栈顶就是父 span），出栈算 latency，异常写 `error` 字段后**原样抛出**——追踪器绝不能吞错。

## token 与成本怎么"自动"归因

`trace.add_usage()` 用 `contextvars` 定位**当前打开的 span**：

```python
# llmops/llm.py 里，LLM 调用返回后：
if trace is not None and resp.usage:
    trace.add_usage(resp.usage.prompt_tokens, resp.usage.completion_tokens, model)
```

因为 `chat()` 总是在某个 `with tr.span(...)` 里被调，usage 自动记到栈顶 span——**业务代码不用改，埋点集中在一个出口**。这是把所有 LLM 调用收敛到 `llmops/llm.py` 一个封装的回报。

成本 = token × 价目表：`PRICE_TABLE` 内置 deepseek-chat 等常见模型的"美元/百万 token"单价，`.env` 里 `PRICE_IN_PER_M`/`PRICE_OUT_PER_M` 可整体覆盖。demo 里一次 RAG 链 $0.0002——数字小，但**没有归因你连这个都不知道**。

## 落盘格式（`llmops/store.py`）

```
runs/
├── index.jsonl              # 每次运行追加一行：run_id/kind/ts/summary/report 摘要
├── <run_id>.jsonl           # 首行 meta + summary，其后每行一个 span 或 case
└── <run_id>.cases.json      # 02 脚本另存的用例明细（badcase 回流人工看）
```

三个设计决定：

1. **JSONL 追加而非改写**：崩溃安全；评估跑到第 8 条断网，前 7 条的 span 已落盘。
2. **index 与明细分离**：仪表盘列表页只读 index（每行几百字节），点开某次运行才读完整文件。
3. **kind 字段分类**（`trace` / `eval_rag` / `eval_agent`）：`04_report.py` 按 kind 找同类运行做对比，Web 按 kind 分组展示。

采样策略（生产话题）：demo 全量记录；线上流量大时按 1% 采样、错误全采——采样决策放 `save_run()` 之前即可，格式不用变。

## 代码对应

| 符号 | 职责 |
|------|------|
| `Trace` / `Span` | trace 容器与单环节记录（`asdict` 直接可序列化） |
| `Trace.span` / `record_span` | 上下文/装饰器两种打点入口，自动父子+延迟+错误 |
| `Trace.add_usage` | contextvars 定位当前 span，记 token 与模型 |
| `estimate_cost_usd` | 价目表成本估算（env 可覆盖） |
| `store.save_run` / `load_run` | JSONL 落盘与读取，index.jsonl 登记 |

## 生产要点

- **messages 快照**：009 课强调"每轮完整 messages"，本教程为控制文件体积只记入参/出参截断（`_INPUT_TRUNC`/`_OUTPUT_TRUNC`）。生产观测平台（Langfuse）会全量存 messages——本地 trace 留"结构与指标"，全量上下文交给平台。
- **trace_id 贯穿**：把 `run_id` 塞进业务日志的 header，一条 trace 能从"用户投诉"追到"具体哪次 LLM 调用"。
- **错误必记**：`error` 字段 + summary 的 `error_count`。线上告警的第一层指标就是 error 率。
- **异步/流式**：本教程同步 API；流式场景 span 结束时机改为"流结束"，token 用累计 usage。

## 思考题

1. `record_span` 装饰器为什么在异常时记录 `error` 后要 `raise` 而不是吞掉？
2. add_usage 用 contextvars 找"当前 span"，这对业务代码的写法提出了什么约束？
3. 为什么 index.jsonl 要冗余存一份 report 摘要，而不是每次都去解析全量 run 文件？

## 参考答案

1. 追踪是旁路设施，不能改变业务语义。吞掉异常会让"评估脚本以为这题过了"，整条 golden set 的通过率变成谎言；记录后原样抛出，调用方（runner）捕获并写进 case 的 error 字段，才是正确的错误流向。
2. 业务代码必须"在某个 span 上下文内"调 LLM——chat() 忘了外面套 span，usage 就落到空栈上丢失。约束就是：**LLM 调用必须发生在打点上下文内**；这也是把 chat() 收敛到单一出口的原因——出口处可以做兜底（本教程退到实例栈），而不是指望每个调用点自觉。
3. 列表页高频、明细页低频。每次渲染列表都解析几十个全量 run 文件是 O(全量 IO)；冗余一份几百字节的 report 摘要进 index，列表页一次顺序读全搞定。冗余换读取效率，是观测系统最常见的取舍。

## 下一步

[05 · 回归流程与 Badcase 回流](05-regression.md)
