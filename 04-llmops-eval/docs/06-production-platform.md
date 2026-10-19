# 06 · 生产观测平台：Langfuse 对照与告警

代码：`scripts/06_langfuse.py`、`requirements-framework.txt`

## 本教程的原生实现 vs 生产平台

前面五课的手写实现（Trace/指标/judge/回归）是**教学最小闭环**——每个环节的原理你都摸过底了。上生产不推荐继续手搓，推荐直接用观测平台。对照关系：

| 本教程 | Langfuse（开源，self-host / cloud） | 说明 |
|--------|-------------------------------------|------|
| `Trace` + `run_id` | Trace | 一次运行一条 |
| `Span` | Generation / Span | LLM 调用用 Generation（自动算成本），其他环节用 Span |
| `runs/*.jsonl` 落盘 | 平台自带存储（clickhouse/pg） | 不用自己管文件 |
| `estimate_cost_usd` 价目表 | 平台内置模型价目（更全、自动更新） | |
| `judge.py` 手写裁判 | Dataset + Metrics + LLM-as-judge 功能 | 平台化管理用例集与人工评分 |
| `04_report.py` 趋势 | 平台 Dashboard | 交互式、可切维度 |
| `05_web.py` 仪表盘 | 平台 UI + API | 生产级，直接替换 |

**为什么先手写再上平台**：直接上平台，你会用它的 Trace 却不理解 span 为什么要分父子、成本怎么归因到环节、judge 为什么要有 coverage。反过来，原生闭环写过一遍后，平台只是"把 exporter 换成上报 SDK"——本课的 `06_langfuse.py` 就是这句话的证明。

## 接入 Langfuse（三步）

```bash
# 1. 装框架依赖（独立于 requirements.txt）
.venv/bin/python -m pip install -r requirements-framework.txt

# 2. .env 填 keys（cloud 或自托管均可）
#   LANGFUSE_PUBLIC_KEY=pk-lf-...
#   LANGFUSE_SECRET_KEY=sk-lf-...
#   LANGFUSE_HOST=https://cloud.langfuse.com

# 3. 跑对照脚本
.venv/bin/python scripts/06_langfuse.py
```

没配 keys 时脚本**打印接入指引后优雅退出（exit 0）**——CI/共享环境里不会因为缺配置炸掉。配好后跑一条与 `01_trace_demo.py` 同构的迷你 RAG 链，`trace.generation()` 上报生成环节，Langfuse UI 的 Traces 里就能看到同样的树。

结构对齐的关键就在 `06_langfuse.py` 里那几行：`lf.trace()` 对应 `Trace()`，`trace.span()` 对应 `tr.span()`，`trace.generation(model=...)` 对应生成环节的 span + usage。**概念一一映射，迁移只是换 API 名。**

## OpenTelemetry 思路（平台无关的第三条路）

不想绑定单一平台，或者公司已有 APM 体系，走 OTel：

```
业务代码 ──otel tracer──→ OTLP exporter ──→ Jaeger/Tempo/Datadog/任意后端
```

与本教程的映射：`Trace`↔otel Trace、`Span`↔otel Span、`add_usage`↔span attributes（`llm.token.usage` 等语义约定）。OpenLLMetry / OpenTelemetry GenAI 语义约定正在收敛 `llm.*` 属性命名，选平台时优先支持该约定的—— exporter 可插拔，埋点不重写。

三条路线的选择：**快速验证用本教程原生版；中小团队直接 Langfuse；已有可观测中台的大团队走 OTel 约定 + 现有后端。**

## 告警指标（观测的目的不是存档，是触发行动）

平台把数据存下来之后，至少盯这四类（阈值按你的基线定）：

| 类别 | 指标 | 告警场景 |
|------|------|---------|
| 可用性 | trace error 率、LLM 调用失败率 | 上游 API 挂了 / key 失效 / 限流 |
| 质量 | judge 忠实度均分、拒答率、用户点踩率 | 新 prompt 引入幻觉潮；知识库过期 |
| 成本 | 单次运行 token/费用、日费用环比 | 某功能被刷量；Agent 死循环烧 token |
| 延迟 | P95 端到端延迟、首字延迟 | 模型变慢 / 上下文膨胀 / 依赖排队 |

注意**告警基线来自离线评估**：你先用 golden set 评估知道"忠实度正常 ≈ 4.8"，线上告警阈值才有依据（比如 < 4.5 持续 30 分钟）。没有离线评估，线上告警只能设"接口挂没挂"，质量类告警无从谈起——这就是本教程 01~05 课存在的意义。

## 生产闭环全景

```
                    ┌──────────── 离线（本教程主线）────────────┐
改 prompt/模型 ──→ 跑 golden set ──→ diff 回归 ──→ 合入/回滚
                    └───────────────────▲─────────────────────┘
                                        │ badcase 回流
                    ┌──────────── 在线（本课）─────────────────┐
用户请求 ──→ 业务 ──→ Tracing 上报（Langfuse/OTel）──→ 看板/告警
                    │                    │                     │
                    │              抽样 judge 评估          点踩/客诉
                    └────────────────────┴─────────────────────┘
```

在线数据喂 badcase 回离线集，离线基线喂告警阈值——两个半圆合上，才是 LLMOps 的完整闭环。

## 代码对应

| 符号 | 职责 |
|------|------|
| `06_langfuse.main` | 读 `LANGFUSE_*`；缺配置打印指引 exit 0；有配置上报同构 trace |
| `requirements-framework.txt` | 框架依赖与教学版 requirements.txt 隔离，教学环境零污染 |

## 生产要点

- **采样**：全量上报成本高；线上按 1% 采样 + 错误/高延迟全采。Langfuse/OTel 都支持采样配置。
- **PII 脱敏**：上报前脱掉用户手机号/订单号——观测平台是新的数据泄露面，密钥与数据都要管。
- **Prompt 版本管理**：平台侧关联 prompt 版本与 trace，"哪版 prompt 的忠实度更高"才有据可查；本教程用 git 管 golden set 与 prompt 文本，同理。
- **数据留存**：trace 全量留存很贵，热存 30 天 + 聚合指标长期留存是常见策略。
- **安全**：Langfuse self-host 注意把 UI 挂内网 + 开鉴权，trace 里是完整业务数据。

## 思考题

1. 为什么"先手写原生闭环再上平台"比"直接上平台"学习路径更优？
2. 告警阈值（如忠实度 < 4.5）为什么必须先有离线评估才能定？
3. 观测平台相比本教程的 JSONL 落盘，多了哪两个必须认真对待的非功能问题？

## 参考答案

1. 平台抽象掉了 span 结构、成本归因、judge 降级这些概念，使用者只会"点按钮看图"，出了噪声（judge 抖动、假回归）无法判断是平台 bug、配置问题还是系统真退化。原生闭环写过一遍后，概念与平台功能一一对应，排障和选型都有底气——迁移成本只是换 exporter，正如 `06_langfuse.py` 所示。
2. 阈值 = 基线 - 噪声余量。没有离线评估，你不知道"正常忠实度"是多少、单次评估的波动范围多大——4.5 对一个基线 4.0 的系统是永远误报，对基线 4.9 的系统又太松。先用 golden set 量出基线与噪声，线上阈值才有物理意义。
3. ①**数据安全/PII**：trace 含完整用户输入输出，平台成了敏感数据新聚集地，需要脱敏、鉴权、访问审计；②**成本与留存治理**：全量上报 + 长期留存的存储费用可观，需要采样策略与冷热分层。JSONL 单机文件不面临这两个问题的量级，生产平台必须直面。

## 回顾与下一步

至此本教程闭环完成：**评估集（01）→ 指标（02）→ 裁判（03）→ 追踪（04）→ 回归（05）→ 平台（06）**。

建议的课后实践：

1. 给 `sut_rag.py` 换一个真实检索实现（接 01 RAG 教程的混合召回），对比 hit@3 变化
2. 给 `judge.py` 加第三个维度"简洁性"，并做一次 30 条人工校准
3. 把 `04_report.py` 接进 git hook，每次提交自动对比 main 分支基线
4. 在 `05_web.py` 上加一个"手动触发评估"按钮（POST /api/runs/eval）
5. docker 自托管 Langfuse，把 `06_langfuse.py` 的 token 用量补全（`gen.end(usage=...)`）
