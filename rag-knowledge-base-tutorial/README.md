# RAG 知识库实战教程

**从零手写一个 RAG 知识库**：不依赖 LangChain/LlamaIndex 等框架，用 ~300 行原生代码讲透 RAG 每一个环节，再给出对接生产级组件（Milvus / pgvector / 重排模型 / FastAPI）的迁移路径。

## 学习路径

| 阶段 | 文档 | 对应代码 |
|------|------|----------|
| 1. 理解原理 | [docs/01-rag-principle.md](docs/01-rag-principle.md) | — |
| 2. 文档分块 | [docs/02-chunking.md](docs/02-chunking.md) | `rag/chunker.py` |
| 3. Embedding 与向量库 | [docs/03-embedding-and-vector-db.md](docs/03-embedding-and-vector-db.md) | `rag/embedder.py` `rag/vector_store.py` |
| 4. 召回与重排 | [docs/04-retrieval-and-rerank.md](docs/04-retrieval-and-rerank.md) | `rag/reranker.py` |
| 5. 生成与 Prompt | [docs/05-generation.md](docs/05-generation.md) | `rag/llm.py` `rag/pipeline.py` |
| 6. 生产化落地 | [docs/06-production.md](docs/06-production.md) | — |
| 7. 框架写法 | [docs/07-frameworks.md](docs/07-frameworks.md) | `scripts/04_llamaindex.py` `scripts/05_langchain.py` |

## 快速开始

### 1. 安装

```bash
cd rag-knowledge-base-tutorial
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 填入你的 LLM API Key
```

> Embedding 和重排默认用**本地模型**（首次运行会自动下载），只有生成环节需要 API Key。
> 召回默认混合（向量+BM25→RRF）；向量库/分块/召回模式三版（原生+两框架）都支持环境变量切换，取值矩阵见 docs/07。

> 框架写法（LlamaIndex / LangChain）需额外安装：`pip install -r requirements-framework.txt`，见下方"框架写法对照"。

### 2. 构建索引（离线）

```bash
python scripts/01_build_index.py
python scripts/01_build_index.py --strategy markdown   # 切换分块方式（recursive/markdown/sentence）
```

会扫描 `data/` 下的示例文档（产品手册 / FAQ / API 文档），完成 分块 → 向量化 → 建 FAISS 索引，输出到 `index/`。

### 3. 提问（在线）

```bash
python scripts/02_query.py "团队版多少钱，几个人可以用？"
python scripts/03_chat.py     # 交互式流式聊天
```

### 4. 框架写法对照（可选）

先跑通原生版再看框架版，每行配置对应原生版哪个环节一目了然（解读见 [docs/07](docs/07-frameworks.md)）：

```bash
pip install -r requirements-framework.txt
python scripts/04_llamaindex.py "团队版多少钱，几个人可以用？"   # LlamaIndex（生产主推）
python scripts/05_langchain.py "团队版多少钱，几个人可以用？"    # LangChain 对照
# 框架版同样支持分块策略切换（详见 docs/07 对照表）：
python scripts/04_llamaindex.py --strategy markdown "团队版多少钱？"
```

## 项目结构

```
rag-knowledge-base-tutorial/
├── README.md
├── requirements.txt
├── requirements-framework.txt  # 框架写法追加依赖（LlamaIndex / LangChain）
├── .env.example              # API Key 与模型配置
├── data/                     # 示例知识库文档
├── rag/                      # 核心代码（原生实现，建议逐文件阅读）
│   ├── chunker.py            # 递归分块 + 重叠窗口
│   ├── embedder.py           # 本地/API 双通道 Embedding
│   ├── vector_store.py       # 可插拔向量库（faiss / sqlite + 统一接口）
│   ├── reranker.py           # Cross-Encoder 重排
│   ├── retriever.py          # BM25（stdlib 中文 bigram）+ RRF 混合融合
│   ├── llm.py                # OpenAI 兼容 LLM（流式）
│   └── pipeline.py           # 端到端 RAG Pipeline
├── scripts/
│   ├── 01_build_index.py     # 离线建索引
│   ├── 02_query.py           # 单次问答（打印检索结果+回答）
│   ├── 03_chat.py            # 交互式聊天
│   ├── 04_llamaindex.py      # 框架写法①：LlamaIndex
│   └── 05_langchain.py       # 框架写法②：LangChain
├── docs/                     # 教程文档（按上方顺序阅读）
└── index/                    # 生成的索引（01 脚本产出）
```

## 一次问答的完整链路

```
用户问题
  │  ① Embedding（查询侧，带 bge 指令前缀）
  ▼
混合召回 top-20（默认）── 向量检索（FAISS/SQLite 内积）
  │                    └─ BM25 关键词检索（精确串/型号）→ RRF 融合
  │  ② Cross-Encoder 重排 → 取 top-4
  ▼
构建 Prompt（资料编号 [1][2]… + 问题）
  │  ③ LLM 生成（流式）
  ▼
带引用来源的回答
```

## 生产迁移要点（详见 docs/06）

- **向量库**：`FaissVectorStore` 接口不变，换成 Milvus / pgvector 实现即可
- **框架**：同样链路的 LlamaIndex / LangChain 写法见 `scripts/04~05`，生产可直接采用 LlamaIndex
- **Embedding**：`bge-small` → `bge-m3`，或迁到托管 API
- **重排**：`bge-reranker-base` → `bge-reranker-v2-m3`
- **服务化**：FastAPI 暴露 `/chat`（SSE 流式），索引构建走后台任务
- **必做**：检索质量评估（命中率/答案相关性）、日志与 Bad case 回流
