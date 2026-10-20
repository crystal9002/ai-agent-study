# LLM 应用评估与观测（LLMOps）实战教程

**给前两个教程（RAG / Agent）配一套"离线评估 + 在线观测"的原生实现**——
不用 torch/HF 模型，评估走 API + 纯 Python 指标，与同目录下的
[RAG 教程](../01-rag-knowledge-base-tutorial/README.md)、
[Agent 教程](../02-agent-tutorial/README.md)同一风格。

场景：**给"智能云盘"问答 RAG 与 Function Calling Agent 建立回归防线**——
改 prompt / 换模型 / 调参数之后，跑一遍 golden set、逐指标 diff、回归标红，
badcase 回流进用例集，形成持续变好的闭环。

## 学习路径

| 阶段 | 文档 | 对应代码 |
|------|------|----------|
| 1. 为什么必须评估（golden set 设计） | [docs/01-why-eval.md](docs/01-why-eval.md) | `data/golden_rag.jsonl` `data/golden_agent.jsonl` |
| 2. 指标体系（硬指标 vs judge） | [docs/02-metrics.md](docs/02-metrics.md) | `llmops/metrics.py` |
| 3. LLM-as-Judge（校准与陷阱） | [docs/03-llm-as-judge.md](docs/03-llm-as-judge.md) | `llmops/judge.py` |
| 4. Tracing（Span 树与成本归因） | [docs/04-tracing.md](docs/04-tracing.md) | `llmops/trace.py` `llmops/store.py` |
| 5. 回归流程与 Badcase 回流 | [docs/05-regression.md](docs/05-regression.md) | `scripts/04_report.py` |
| 6. 生产观测平台（Langfuse 对照） | [docs/06-production-platform.md](docs/06-production-platform.md) | `scripts/06_langfuse.py` |

## 快速开始

### 1. 安装（Python 3.12 + uv）

```bash
cd 04-llmops-eval
uv venv --python /usr/local/bin/python3.12 .venv
uv pip install -p .venv/bin/python -r requirements.txt
cp .env.example .env   # 填 OPENAI_BASE_URL / OPENAI_API_KEY / LLM_MODEL
```

### 2. 追踪演示（Span 树 + 成本归因）

```bash
.venv/bin/python scripts/01_trace_demo.py
# 或自定义问题：
.venv/bin/python scripts/01_trace_demo.py "团队版一年多少钱？"
```

输出一棵 span 树（retrieve → generate → judge×2，含 token/延迟/成本），落盘 `runs/<run_id>.jsonl`。

### 3. 离线评估

```bash
.venv/bin/python scripts/02_eval_rag.py                 # RAG golden set 全量 12 条（含 judge）
.venv/bin/python scripts/02_eval_rag.py --no-judge      # 只跑硬指标（省钱/CI 门禁）
.venv/bin/python scripts/03_eval_agent.py               # Agent golden set 8 条：成功率/工具正确率/轮次
```

### 4. 回归对比

```bash
.venv/bin/python scripts/04_report.py                    # 趋势 + 自动对比最近两次同类评估
.venv/bin/python scripts/04_report.py --kind eval_agent
.venv/bin/python scripts/04_report.py --old <run_id> --new <run_id>
```

指标下降超阈值（默认 0.05）标 🔴 回归，上升标 🟢。

### 5. Web 仪表盘

```bash
.venv/bin/python scripts/05_web.py        # 打开 http://127.0.0.1:8003
```

运行列表 → 点击看 span 树（缩进展示）与用例明细 → 底部评估历史表格 + 通过率 SVG 趋势。前端原生单文件 HTML/JS，8s 轮询（评估是离线批量的，不需要 SSE）。

### 6. Langfuse 对照（可选）

```bash
.venv/bin/python -m pip install -r requirements-framework.txt
# .env 填 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY 后：
.venv/bin/python scripts/06_langfuse.py   # 没配 keys 则打印接入指引后优雅退出
```

### 7. 跨教程闭环：评估 03 的知识库（可选）

用本教程的评估框架（golden set / hit@k / judge / runs 落盘）评估 `03-knowledge-base-agent` 的混合检索+生成。03 的 KB 以 importlib 方式加载为外部 SUT；评估数据是本目录 `data/golden_kb.jsonl`（10 条，星云笔记语料）。需要 03 教程的 venv（faiss/sentence-transformers 在那边）：

```bash
cd 04-llmops-eval
HF_HUB_OFFLINE=1 ../03-knowledge-base-agent/.venv/bin/python scripts/07_eval_kb.py --no-judge   # 只跑硬指标
HF_HUB_OFFLINE=1 ../03-knowledge-base-agent/.venv/bin/python scripts/07_eval_kb.py               # 含 LLM judge
```

跑通后 hits 全绿、hit@3=100%；`llmops/runner.py` 的 `run_rag_eval(..., sut=...)` 就是这次打通的注入点——评估框架与被测系统解耦，换成你们自己的 RAG 只需实现 `rag_query(question, k)`。

## 项目结构

```
04-llmops-eval/
├── README.md
├── requirements.txt / requirements-framework.txt   # 教学版（轻量） / 框架对照版（langfuse）
├── .env.example / .env                             # LLM 配置 + HOST/PORT(8003) + 阈值
├── data/
│   ├── golden_rag.jsonl        # 12 条：{id, question, expected_chunks, expected_answer_contains, type}
│   ├── golden_agent.jsonl      # 8 条：{id, goal, must_call_tools, success_regex/expected_contains, max_turns}
│   └── golden_kb.jsonl         # 10 条：评估 03 知识库的星云笔记语料（scripts/07_eval_kb.py）
├── llmops/                     # 原生实现（逐文件阅读）
│   ├── trace.py                # Trace/Span：装饰器+上下文打点、token/成本归因、JSONL 结构
│   ├── metrics.py              # containment/regex/hit@k/precision@k/mrr + 聚合（judge 降级跳过）
│   ├── judge.py                # LLM-as-judge：忠实度/相关性 1~5，JSON 解析+重试+降级 None
│   ├── runner.py               # 跑 golden set：RAG 检索+生成打分、Agent 成功断言、汇总 report
│   ├── store.py                # runs/ 目录：index.jsonl 登记、落盘、读取（供报告与仪表盘）
│   ├── llm.py                  # OpenAI 兼容 chat 统一出口（usage 自动记入当前 span）
│   ├── sut_rag.py              # 被测 RAG：关键词假检索 + 真 LLM 生成（接口同 01 教程，可替换）
│   └── sut_agent.py            # 被测 Agent：search/calculator/get_time 三工具 Function Calling 循环
├── scripts/
│   ├── 01_trace_demo.py        # 迷你 RAG 链打 span，落盘并打印树状报告
│   ├── 02_eval_rag.py          # 全量 RAG 评估：命中率/containment/judge 分
│   ├── 03_eval_agent.py        # Agent 评估：成功率/工具正确率/平均轮次
│   ├── 04_report.py            # 趋势 + 两次运行 diff（回归标红）
│   ├── 05_web.py               # FastAPI 仪表盘（端口 8003：/api/runs /api/runs/{id} /api/evals）
│   ├── 06_langfuse.py          # Langfuse 对照（缺配置打印指引优雅退出）
│   └── 07_eval_kb.py           # 跨教程闭环：用本框架评估 03 的 KB（外部 SUT 注入）
├── web/index.html              # 单页仪表盘（原生 JS，绝对路径 /api/*）
├── runs/                       # 评估/追踪落盘（.gitignore 忽略）
└── docs/                       # 6 篇教程（按学习路径阅读）
```

## 一次评估运行的链路

```
golden set (data/golden_rag.jsonl)
 │ 逐条
 ▼
┌─ run_rag_case（runner.py）────────────────────────────┐
│ ① 被测管线 SUT：关键词检索 → LLM 生成     sut_rag.py  │ ← 每个环节包一层 Span
│    （LLM 调用经 llm.py → add_usage 记入当前 span）    │    trace.py 记 token/延迟/成本
│ ② 硬指标：hit@3 / precision@3 / mrr / containment     │ ← metrics.py
│ ③ 软指标：judge 忠实度+相关性（失败降级 null）        │ ← judge.py
└──────────────────────────────────────────────────────┘
 │ 全量跑完
 ▼
aggregate() 聚合 report ──→ store.py 落盘 runs/<run_id>.jsonl + 登记 index.jsonl
 │                              │
 ▼                              ▼
控制台表格 + *.cases.json    04_report.py 趋势/diff（回归🔴）  05_web.py 仪表盘(8003)
                                    │
                                    ▼
                          badcase 归因 → 回流 golden set（闭环）
```

## 两个核心设计一句话区分

- **硬指标 vs LLM-as-judge**：containment/hit@k 便宜稳定但死板（CI 门禁首选）；judge 懂语义但贵且有噪声（发版前与人工抽检用）——双轨并行，`judge_coverage` 防裁判失效变盲区。
- **过程断言 vs 结果断言**：Agent 只断言答案会"蒙对"；`must_call_tools`（过程）+ `success_regex`（结果）+ `max_turns`（成本）三条腿才是可上线的断言。

生产化落地（采样上报、告警阈值、OTel、PII 脱敏）见 [docs/06-production-platform.md](docs/06-production-platform.md)。
