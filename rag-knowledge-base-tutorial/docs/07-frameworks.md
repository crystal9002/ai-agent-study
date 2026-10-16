# 07 · 框架写法：LlamaIndex 与 LangChain

对应代码：`scripts/04_llamaindex.py`、`scripts/05_langchain.py`
（需额外安装：`pip install -r requirements-framework.txt`）

同样的需求，三种写法对比：

| | 原生实现（本教程主体） | LlamaIndex | LangChain |
|---|---|---|---|
| 代码量 | ~300 行 | **~50 行** | ~80 行 |
| 抽象粒度 | 每个环节自己写 | RAG 专用组件，开箱即用 | 通用 LLM 链，拼装自由 |
| 可控性 | 完全可控 | 需钻源码时略绕 | 抽象层多，调试链路长 |
| 适合 | 学原理、定制核心链路 | **生产 RAG 主流选择** | 多环节编排的通用 LLM 应用 |

## LlamaIndex 版（scripts/04_llamaindex.py）

对照原生版逐行看，框架把每个环节封装成了配置：

```python
# 原生版                          # LlamaIndex 版
rag/embedder.py（自己写）    →    Settings.embed_model = HuggingFaceEmbedding(...)
rag/llm.py（自己写）        →    Settings.llm = OpenAILike(...)
rag/chunker.py（自己写）     →    Settings.chunk_size / chunk_overlap
01_build_index.py（自己写）  →    SimpleDirectoryReader + VectorStoreIndex
rag/reranker.py（自己写）    →    SentenceTransformerRerank(top_n=4)
pipeline.query()（自己写）   →    index.as_query_engine(...).query()
```

三个值得注意的封装：

1. **`VectorStoreIndex.from_documents()`**：加载、递归分块、向量化、入库一步完成。
2. **`query_engine`**：检索 + 重排 + 生成一条链，`similarity_top_k` / `node_postprocessors` 即召回数与重排器。
3. **`response.source_nodes`**：引用溯源内置——每条返回带得分和原文，不用自己拼。

持久化：`storage_context.persist()` 落盘，下次 `load_index_from_storage()` 直接加载（脚本已自动处理）。

## 分块策略切换（两版框架脚本均支持）

与原生版同一个开关：`--strategy` 命令行参数或环境变量 `CHUNK_STRATEGY`
（`recursive` / `markdown` / `sentence`），切换后**各自重建自己的索引缓存**
（框架版缓存目录已按策略隔离：`index_llamaindex/<strategy>`、`index_langchain/<strategy>`）：

```bash
python scripts/04_llamaindex.py --strategy markdown "团队版多少钱？"
python scripts/05_langchain.py --strategy sentence "团队版多少钱？"
```

三种写法的对应关系（注意框架与原生的粒度差异，已实测）：

| 策略 | 原生 `rag/chunker.py` | LlamaIndex `04` | LangChain `05` |
|------|----------------------|-----------------|----------------|
| recursive（默认） | 字符：段落→句子递归 + 重叠 | `SentenceSplitter`（**token 单位**，1 token≈1~1.5 中文字） | `RecursiveCharacterTextSplitter` |
| markdown | 按 `#` 切章节，超长章节递归兜底，短章节合并 | `MarkdownNodeParser`（纯结构切，**不保证 chunk_size**，可能产生只有标题的小块） | `MarkdownTextSplitter` |
| sentence | 句子滑窗 + 重叠 | `SentenceSplitter` + 永不匹配的 `paragraph_separator`（跳过段落分组） | `RecursiveCharacterTextSplitter(separators=[句号/问号…])` |

结论：**框架的"同名策略"只是同类思路，切分结果不会与原生版逐块一致**——换框架要重跑评估，不能假设索引等价。

## 混合召回（两版框架脚本均支持，默认 hybrid）

同一开关 `RETRIEVAL_MODE=hybrid|vector`（`.env`），三版默认都是混合（向量+BM25→RRF→重排），
但接线方式不同，正好演示"原生组件如何长进框架"：

| | 原生 `rag/pipeline.py` | LlamaIndex `04` | LangChain `05` |
|---|---|---|---|
| BM25 | `rag/retriever.py::BM25Index` | **自定义 `BM25NodeRetriever`**（20 行适配层，内部就是原生 BM25Index） | 直接复用 `rag/retriever.py`（langchain 生态的 BM25Retriever 中文需另配 jieba） |
| 融合 | `rrf_fuse()` | `QueryFusionRetriever(mode="reciprocal_rerank")`（LlamaIndex 的 RRF 实现） | `rrf_fuse()`（同原生） |
| 向量路 | `store.search()` | `index.as_retriever(similarity_top_k=20)` | `store.similarity_search_with_score()` |

要点：

1. **LlamaIndex**：`QueryFusionRetriever` 内置 RRF（参数名 `reciprocal_rerank`），`num_queries=1` 时不调 LLM 改写查询；没有开箱即用的中文 BM25，所以写了 `BM25NodeRetriever(BaseRetriever)` 演示自定义组件接入。
2. **LangChain**：生态有 `EnsembleRetriever`，但其 BM25Retriever 默认按空格分词、中文要自己配 jieba——不如直接复用原生 `BM25Index + rrf_fuse`，**框架脚本 import 原生组件完全合法**。
3. 切 `RETRIEVAL_MODE=vector` 可与 hybrid 做对照实验（三版均可）。

## 向量库切换（同一开关 `VECTOR_STORE`，取值属于各自生态）

| 后端 | 原生 `rag/vector_store.py` | LlamaIndex `04` | LangChain `05` |
|------|---------------------------|-----------------|----------------|
| 默认 | `faiss`（IndexFlatIP） | **`simple`**（内置 SimpleVectorStore，dict+JSON 落盘，零依赖） | `faiss` |
| 可选 | `sqlite`（stdlib 单文件） | `faiss`（需 `llama-index-vector-stores-faiss`；向量文件 `faiss.idx` + docstore 分开持久化） | **`sqlite`**（自定义 `SQLiteVectorStore(LangChain VectorStore)` 适配层，内部复用原生 `SqliteVectorStore`） |
| 生产 | pgvector / Qdrant / Milvus | pgvector / Qdrant / Milvus（官方集成包） | pgvector / Chroma / Qdrant |

```bash
VECTOR_STORE=sqlite python scripts/01_build_index.py       # 原生
VECTOR_STORE=faiss  python scripts/04_llamaindex.py "…"    # LlamaIndex
VECTOR_STORE=sqlite python scripts/05_langchain.py "…"     # LangChain
```

注意：

1. **同名不同义**：`VECTOR_STORE=sqlite` 在 LlamaIndex 脚本会报错并提示改用 `simple|faiss`（其生态的单机库是 Simple/FAISS，SQL 系走 pgvector）——报错信息里写了各版可选值。
2. **适配层模式**（05 的 `SQLiteVectorStore`）：框架的存储接口（LangChain `VectorStore` / LlamaIndex `VectorStore`）实现 3~4 个方法即可挂上任意后端，是接自研存储的标准姿势；05 演示 LangChain 版、原生 `SqliteVectorStore` 提供全部逻辑。
3. 缓存目录按（策略 × 后端）隔离：`index_llamaindex/<strategy>/<store>`、`index_langchain/<strategy>/<store>`，切换后端自动重建、不读错缓存。
4. 无论哪版，**换后端必须用同一 Embedding 模型重建**，向量空间不通用。

## LangChain 版（scripts/05_langchain.py）


LangChain 的核心是 **LCEL（链式表达符语言）**，用 `|` 把组件串成数据流：

```python
chain = (
    {"context": fmt, "question": RunnablePassthrough()}   # 组装输入
    | PROMPT                                              # 渲染模板
    | ChatOpenAI(...)                                     # 调模型
    | StrOutputParser()                                   # 取字符串
)
chain.stream(question)   # 天然支持流式
```

对应关系：`DirectoryLoader/TextLoader` → 加载；`RecursiveCharacterTextSplitter` → 分块；`HuggingFaceEmbeddings + FAISS` → 向量库；`as_retriever(k=20)` → 召回。重排 LangChain 生态多为第三方封装（cohere/flashrank），本脚本直接复用 `sentence-transformers` 的 CrossEncoder，效果与原生版一致。

## 怎么选（生产建议）

1. **要快速上线、团队没有深度定制需求** → **LlamaIndex**（RAG 专用，检索/评估/数据接入组件最全）。
2. **项目以 LLM 编排为主（RAG 只是其中一环）** → LangChain，或 LlamaIndex + LangChain 混用（LlamaIndex 做检索，LangChain 做业务编排，二者有官方集成）。
3. **RAG 是核心竞争力、有定制检索/排序策略** → 原生自研（大厂常见做法），框架只借鉴其组件设计。
4. **无论用不用框架，前四步的质量都不变**：分块、Embedding 选型、召回+重排、评估——这些是领域知识，框架只是少写胶水代码，不会替你做好。

> 实践建议：先跑通 `scripts/01~03`（原生版）理解每个环节，再跑 `04/05` 对照，你会清楚框架每行配置到底在做什么。

## 回到

[README](../README.md) · 生产化清单见 [06-production.md](06-production.md)
