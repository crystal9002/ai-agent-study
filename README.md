# 从零开始学 AI Agent

一套**从零开始、动手跑通**的 AI Agent 学习教程：先打好 RAG 基础，再进阶到任务规划型 Agent。每个教程都是「原生实现讲透原理 → 框架写法对接生产」双版本，配套 5~7 篇渐进式文档 + 可直接运行的代码。

## 学习路径

```
第 1 步：RAG 知识库（Agent 的"长期记忆"与 grounding 基础）
   │   理解：分块 / Embedding / 向量库 / 混合召回 / 重排 / 生成
   ▼
第 2 步：任务规划型 Agent（LLM + 工具 + 循环）
   │   理解：Function Calling / ReAct / Plan-and-Execute
   ▼
第 3 步：生产化（评估、状态持久化、人工确认、工具网关）← docs/05、06
```

## 教程目录

### 1. [RAG 知识库实战](rag-knowledge-base-tutorial/README.md)

不依赖框架，~400 行原生代码实现完整 RAG，再给 LlamaIndex / LangChain 对照版。

- **原生**：分块策略可切（recursive/markdown/sentence）、向量库可插拔（faiss/sqlite）、混合召回默认开（向量+BM25→RRF）、Cross-Encoder 重排、流式生成带引用
- **框架**：LlamaIndex（生产主推）+ LangChain 双版本，同一开关切换分块/召回/存储
- **文档**：01 原理 → 02 分块 → 03 向量库 → 04 召回重排 → 05 生成 → 06 生产化 → 07 框架对照

```bash
cd rag-knowledge-base-tutorial
pip install -r requirements.txt && cp .env.example .env  # 填 API Key
python scripts/01_build_index.py                          # 建库
python scripts/02_query.py "团队版多少钱，几个人可以用？"   # 问答
python scripts/06_web.py                                  # Web 界面 → http://127.0.0.1:8000
```

### 2. [任务规划型 Agent 实战](agent-tutorial/README.md)

从零手写 Plan-and-Execute Agent：给它一个目标，它自己拆计划、调工具、交方案。

- **原生**：工具注册表（签名自动推 Schema）、Function Calling 循环、结构化规划、逐步执行与汇总，含 7 个差旅场景工具（查航班/酒店/天气/写日历/安全求值）
- **框架**：LangGraph 版（`@tool` + `with_structured_output` + `StateGraph` 状态图）
- **文档**：01 Agent 原理 → 02 工具调用 → 03 规划执行 → 04 LangGraph → 05 生产化

```bash
cd agent-tutorial
pip install -r requirements.txt && cp .env.example .env  # 填 API Key
python scripts/01_task_agent.py "下周二到周四去上海出差，帮我安排行程"
python scripts/03_web.py                                  # Web 界面 → http://127.0.0.1:8001
```

## 两个教程怎么配合

| | RAG 教程 | Agent 教程 |
|---|---|---|
| 解决什么 | 让 LLM **答得准**（查得到资料） | 让 LLM **做得成事**（多步任务闭环） |
| 核心链路 | 检索 → 重排 → 生成 | 规划 → 工具调用 → 观察 → 汇总 |
| 共用组件 | Embedding / 重排 / LLM 封装风格一致，`.env` 配置通用 | |
| 进阶组合 | 把 RAG 的检索能力包成 Agent 的一个工具，即"查知识库的 Agent" | |

## 环境要求

- Python 3.10+
- 一个 OpenAI 兼容 API（OpenAI / DeepSeek / 方舟 / 自建 vLLM 均可，改 `.env` 即可）
- Embedding 与重排默认**本地运行**（首次自动下载模型），不强制要 GPU

## 阅读建议

1. 先跑通原生版脚本，对照 `docs/` 理解每个环节为什么存在
2. 每个教程的最后一篇（`06-production` / `05-production`）是生产落地清单，面试与实战都用得上
3. 改参数要有评估意识：分块/召回/存储切换后，用固定问题集对比效果再决策
