# 03 · Embedding 与向量库

代码：`rag/embedder.py`、`rag/vector_store.py`

## Embedding：把文本变成向量

Embedding 模型把文本映射到高维空间，**语义相近的文本距离相近**。"怎么退款"和"退款流程"字面不同，但向量很接近——这就是 RAG 能做语义检索的原因。

### 本项目的双通道实现

```python
# .env 控制
EMBEDDING_PROVIDER=local   # 默认：本地 sentence-transformers
EMBEDDING_PROVIDER=api     # 切到 OpenAI 兼容 API
```

- `LocalEmbedder`：加载 `BAAI/bge-small-zh-v1.5`，CPU 也能跑，免费、无外呼。
- `APIEmbedder`：调 OpenAI 兼容 `/embeddings`，适合无 GPU 或统一走 API 网关的团队。

**关键细节（bge 系列特有）**：查询侧要加指令前缀「为这个句子生成表示以用于检索相关文章：」，文档侧不加。`encode(texts, is_query=True)` 已自动处理——加错或漏加会显著降低检索效果。

### 模型选型（中文场景）

| 模型 | 维度 | 特点 |
|------|------|------|
| bge-small-zh-v1.5 | 512 | 快、小，本教程默认，效果够用 |
| bge-large-zh-v1.5 | 1024 | 效果/速度平衡，单机首选 |
| **bge-m3** | 1024 | 当前中文综合最优，支持 8K 长文本与多语言，**生产推荐** |
| text-embedding-3-small | 1536 | OpenAI 托管，免运维 |

**铁律：查询侧和文档侧必须用同一个模型、同一套前缀规则。** 换模型必须全库重建索引。

### 归一化

余弦相似度 = 归一化后的内积。本项目在 embedder 里就把向量归一化，向量库直接用内积（`IndexFlatIP`），少一次运行时计算。

## 向量库：FAISS 本教程实现

`FaissVectorStore` 三个核心方法，也是所有向量库的通用抽象：

```python
build(vectors, chunks)   # 建索引
search(query_vec, top_k) # 返回 [(chunk, 余弦分数)]
save()/load()            # 持久化到 index/
```

`IndexFlatIP` 是**暴力精确检索**（逐一算内积）：百万级以内毫秒级返回，且 100% 召回。它是精确的，所以本教程的检索分数可以直接信任。

## 生产向量库对比

| 方案 | 适用规模 | 选它当… |
|------|---------|--------|
| FAISS（本项目） | < 100 万 | 单机、嵌入式、原型 |
| **pgvector** | < 500 万 | 已有 PostgreSQL，不想多运维一个组件（**多数团队的最优解**） |
| **Qdrant** | 千万级 | 要独立向量库、Rust 高性能、过滤条件丰富 |
| **Milvus** | 亿级以上 | 需要分布式扩容、多租户（**大规模生产事实标准**） |
| Elasticsearch | 已有 ES | 搜索基建现成，向量+关键词混合检索 |

### 切换存储后端（本项目支持 2 种，接口统一）

`rag/vector_store.py` 定义了 `VectorStore` 抽象接口（`build / search / save / load`），
所有后端实现同一契约，业务代码（`pipeline.py`）零感知：

| 后端 | 实现 | 特点 |
|------|------|------|
| `faiss`（默认） | `FaissVectorStore` | IndexFlatIP 精确检索，百万级毫秒返回 |
| `sqlite` | `SqliteVectorStore` | stdlib 零依赖；向量+文本**单文件**、可 SQL 过滤（doc_id/租户）、易备份 |

```bash
# 方式一：环境变量（.env）
VECTOR_STORE=sqlite
python scripts/01_build_index.py    # 产物：index/vectors.db
python scripts/02_query.py "团队版多少钱"

# 方式二：shell 临时切换
VECTOR_STORE=sqlite python scripts/01_build_index.py
```

两个后端在 `index/` 里各写各的产物（`index.faiss+chunks.json` / `vectors.db`），**互不干扰，
但向量必须同一 Embedding 模型**——换后端也要重建索引，不能只换名加载。

生产扩展同理：实现 pgvector/Milvus/Qdrant 后在 `STORE_BACKENDS` 注册一行
（`pipeline` 与脚本自动可切换）。以 pgvector 为例，SQL 语义与 `SqliteVectorStore` 同源：

```python
class PgVectorStore(VectorStore):
    def build(self, vectors, chunks):
        # INSERT INTO chunks (embedding, text, ...) VALUES ($1, $2)
        ...
    def search(self, query_vec, top_k):
        # SELECT ... ORDER BY embedding <=> $1 LIMIT $2   （<=> 余弦距离）
        ...
```

存储结构要点：**向量 + payload（chunk 原文与元数据）一起入库**，检索时一并取出；为常用过滤字段（doc_id、tenant_id、时间）建索引。更多见 [06-production.md](06-production.md)。

## 混合检索（生产标配，强烈建议）

纯向量检索对**专有名词、型号、编号**（如 "XH-3000"、"ERR_4021"）不敏感。生产系统通常做：

```
向量检索(语义) + BM25 关键词检索(精确) → RRF 融合排序 → 重排
```

Elasticsearch / Qdrant / Milvus 2.5+ 都原生支持。本教程已实现（stdlib BM25 + RRF，
`RETRIEVAL_MODE=hybrid` 默认开启），实现与切换见 [04 · 召回与重排](04-retrieval-and-rerank.md)。

## 下一步

[04 · 召回与重排](04-retrieval-and-rerank.md)
