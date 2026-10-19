# 从零开始学 AI Agent

一套**从零开始、动手跑通**的 AI Agent 学习教程：先打好 RAG 基础，再进阶到任务规划型 Agent，然后是组合、评估、安全、多智能体四门生产实战。每个教程都是「原生实现讲透原理 → 框架写法对接生产」双版本，配套 5~7 篇渐进式文档 + 可直接运行的代码，文件夹带序号按序学习。

## 学习路径

```
第 1 步：01 RAG 知识库（Agent 的"长期记忆"与 grounding 基础）
   │   理解：分块 / Embedding / 向量库 / 混合召回 / 重排 / 生成
   ▼
第 2 步：02 任务规划型 Agent（LLM + 工具 + 循环）
   │   理解：Function Calling / ReAct / Plan-and-Execute
   ▼
第 3 步：03 知识库 Agent（把 RAG 检索包成工具，组合范式）
   │   理解：工具与检索混合编排 / 引用溯源 / 防幻觉合同
   ▼
第 4 步：04 评估与观测（LLMOps，改一版 prompt 不退化的底气）
   │   理解：golden set / 指标体系 / LLM-as-judge / tracing / 回归
   ▼
第 5 步：05 Agent 安全（能力越大越要收敛）
   │   理解：注入隔离 / 权限沙箱 / 人工审批 / 审计与红队
   ▼
第 6 步：06 MCP 与多智能体（集成协议 + 任务分发协作）
         理解：MCP server/client / supervisor-worker / LangGraph 对照
```

## 教程目录

### 1. [RAG 知识库实战](01-rag-knowledge-base-tutorial/README.md)

不依赖框架，~400 行原生代码实现完整 RAG，再给 LlamaIndex / LangChain 对照版。

- **原生**：分块策略可切（recursive/markdown/sentence）、向量库可插拔（faiss/sqlite）、混合召回默认开（向量+BM25→RRF）、Cross-Encoder 重排、流式生成带引用
- **框架**：LlamaIndex（生产主推）+ LangChain 双版本，同一开关切换分块/召回/存储
- **文档**：01 原理 → 02 分块 → 03 向量库 → 04 召回重排 → 05 生成 → 06 生产化 → 07 框架对照

```bash
cd 01-rag-knowledge-base-tutorial
pip install -r requirements.txt && cp .env.example .env  # 填 API Key
python scripts/01_build_index.py                          # 建库
python scripts/02_query.py "团队版多少钱，几个人可以用？"   # 问答
python scripts/06_web.py                                  # Web 界面 → http://127.0.0.1:8000
```

### 2. [任务规划型 Agent 实战](02-agent-tutorial/README.md)

从零手写 Plan-and-Execute Agent：给它一个目标，它自己拆计划、调工具、交方案。

- **原生**：工具注册表（签名自动推 Schema）、Function Calling 循环、结构化规划、逐步执行与汇总，含 7 个差旅场景工具（查航班/酒店/天气/写日历/安全求值）
- **框架**：LangGraph 版（`@tool` + `with_structured_output` + `StateGraph` 状态图）
- **文档**：01 Agent 原理 → 02 工具调用 → 03 规划执行 → 04 LangGraph → 05 生产化

```bash
cd 02-agent-tutorial
pip install -r requirements.txt && cp .env.example .env  # 填 API Key
python scripts/01_task_agent.py "下周二到周四去上海出差，帮我安排行程"
python scripts/03_web.py                                  # Web 界面 → http://127.0.0.1:8001
```

### 3. [知识库 Agent（RAG × Agent 组合）](03-knowledge-base-agent/README.md)

把检索能力包成 Agent 的一个工具：多步任务里自己决定"查不查、查什么"，基于证据回答并带引用。

- **原生**：精简 RAG（向量+BM25→RRF）+ ReAct 单循环 + 工具注册表，组合任务示例（查价 → 算账 → 写文件）
- **框架**：LangGraph 版（`@tool` 包 `search_kb` + `create_react_agent`）
- **文档**：01 为什么组合 → 02 检索即工具 → 03 原生循环 → 04 LangGraph → 05 生产化

```bash
cd 03-knowledge-base-agent
pip install -r requirements.txt && cp .env.example .env
python scripts/01_build_kb.py                                              # 建库
python scripts/02_kb_agent.py "团队版多少钱？50个人一年多少钱？"            # CLI
python scripts/03_web.py                                  # Web 界面 → http://127.0.0.1:8002
```

### 4. [评估与观测 LLMOps](04-llmops-eval/README.md)

给前两个教程配一套「离线评估 + 在线追踪」：改 prompt 后跑一遍就知道有没有退化。

- **原生**：span 追踪（token/成本/延迟落盘）、golden set 评估器（hit@k / containment / 任务成功率）、LLM-as-judge（忠实度/相关性）、回归对比报告
- **框架**：Langfuse 对照（`06_langfuse.py`，未配 Key 打印接入指引）
- **文档**：01 为什么评估 → 02 指标 → 03 LLM-as-judge → 04 tracing → 05 回归闭环 → 06 生产平台

```bash
cd 04-llmops-eval
pip install -r requirements.txt && cp .env.example .env
python scripts/01_trace_demo.py        # trace 落盘演示
python scripts/02_eval_rag.py          # golden set 全量评估
python scripts/05_web.py                                   # 仪表盘 → http://127.0.0.1:8003
```

### 5. [Agent 安全实战](05-agent-security/README.md)

三道防线：注入内容隔离 → 工具权限与路径沙箱 → 危险操作人工审批，附 3 个攻击场景的"裸 vs 加固"对照演示。

- **原生**：注入特征库 + `[UNTRUSTED]` 包装、三级权限（read/write/destructive）、realpath 沙箱、审批状态机（default-deny）、JSONL 审计
- **框架**：guardrails-ai Validator 对照（混淆矩阵输出）
- **文档**：01 威胁模型 → 02 注入 → 03 权限沙箱 → 04 人工审批 → 05 审计红队 → 06 框架与纵深

```bash
cd 05-agent-security
pip install -r requirements.txt && cp .env.example .env
python scripts/01_attack_demo.py       # 3 场景：裸 Agent 中招 3/3，加固拦截 3/3
python scripts/03_web.py          # 审批界面 → http://127.0.0.1:8004
```

### 6. [MCP 与多智能体](06-mcp-multi-agent/README.md)

手写一个 MCP server 接进 Agent，再手写 supervisor/worker 多智能体分发协作。

- **原生**：FastMCP stdio server + 客户端桥接（MCP tools → Function Calling schema）、消息总线、supervisor 结构化路由 + 3 个 worker
- **框架**：LangGraph 多智能体对照（StateGraph + 条件边）
- **文档**：01 为什么 MCP → 02 写 server → 03 客户端桥接 → 04 多智能体 → 05 LangGraph → 06 生产化

```bash
cd 06-mcp-multi-agent
pip install -r requirements.txt && cp .env.example .env
python scripts/02_mcp_agent.py "50人团队版一年多少钱？"     # Agent 经 MCP 检索+计算
python scripts/03_multi_agent.py                            # supervisor/worker 分发
python scripts/04_web.py                                    # 泳道可视化 → http://127.0.0.1:8005
```

## 六个教程怎么配合

| 教程 | 解决什么 | 与前后的关系 |
|---|---|---|
| 01 RAG | 让 LLM **答得准**（查得到资料） | 被 03 包成工具 |
| 02 Agent | 让 LLM **做得成事**（多步任务闭环） | 循环被 03/06 复用 |
| 03 知识库 Agent | 检索与多步任务**混合编排** | 用到 01+02，产出交给 04 评估 |
| 04 评估观测 | 改一版 prompt **不退化** | 评估 01/02/03 的产出 |
| 05 安全 | 能力越大**越收敛**（注入/权限/审批） | 给 02/03/06 的工具层加防线 |
| 06 MCP 多智能体 | 集成**外部工具生态** + 任务分发 | 02 单 Agent 的横向扩展 |

共用约定：`.env` 配置通用（OPENAI_BASE_URL / OPENAI_API_KEY / LLM_MODEL），LLM 封装风格一致，Web 界面均为 FastAPI + SSE、按端口 8000~8005 区分。

## 环境要求

- Python 3.10+
- 一个 OpenAI 兼容 API（OpenAI / DeepSeek / 方舟 / 自建 vLLM 均可，改 `.env` 即可）
- Embedding 与重排默认**本地运行**（首次自动下载模型），不强制要 GPU

## 阅读建议

1. 先跑通原生版脚本，对照 `docs/` 理解每个环节为什么存在
2. 每个教程的最后一篇（`*-production` / `06-frameworks` 等）是生产落地清单，面试与实战都用得上
3. 改参数要有评估意识：分块/召回/存储切换后，用固定问题集对比效果再决策
