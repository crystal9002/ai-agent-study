# 04 · 召回与重排：两段式检索

代码：`rag/reranker.py`、`rag/pipeline.py::retrieve()`

## 为什么要两段式

| | 召回（Recall） | 重排（Rerank） |
|---|---|---|
| 模型 | 向量"双塔"：query、doc **分别**编码 | Cross-Encoder：query+doc **拼在一起**过模型 |
| 速度 | 快（doc 向量可离线算好） | 慢（每次都要过一遍模型） |
| 准确度 | 一般 | 高 |
| 职责 | 从百万条里海选出 50~100 条**不漏** | 从 100 条里精选 3~5 条**排对** |

双塔相似度只比较两个独立向量，"貌合神离"的文本也能得高分；Cross-Encoder 让 query 和文档逐 token 交互，能捕捉"问题和答案的精确对应关系"，但无法预算——所以只能用于少量候选。**速度与精度的分工，就是两段式检索的全部意义。**

数据：业界普遍经验，rerank 能把 Top-3 命中率再提升 10~30%，**生产 RAG 的标配**。

## 本项目实现

```python
# pipeline.retrieve() 中
hits = self.store.search(q_vec, top_k=20)                       # ① 粗召回
reranked = self.reranker.rerank(question, [c.text for c,_ in hits], top_n=4)  # ② 精排
```

`CrossEncoderReranker` 默认加载 `BAAI/bge-reranker-base`：

- `RERANK_ENABLED=0` 可关闭（调试提速）
- 中文生产推荐升级 `BAAI/bge-reranker-v2-m3`（改 `.env` 的 `RERANK_MODEL` 即可）

## 参数调优

| 参数 | 建议值 | 说明 |
|------|--------|------|
| `top_k`（召回） | 20~100 | 越大越不容易漏，但重排耗时线性增加 |
| `top_n`（送入 LLM） | 3~5 | 太多会稀释注意力、撑爆上下文 |
| 重排得分阈值 | 实测而定 | 低于阈值宁可答"资料里没有"，避免硬凑 |

**一个实用技巧**：对重排分数设下限。分数普遍很低时，说明知识库没有相关内容，此时应触发"拒答"而不是让 LLM 强行组织语言——这是抑制幻觉最有效的一招（`pipeline.query()` 可扩展此逻辑，作为课后练习）。

## 混合检索（本项目已实现）

代码：`rag/retriever.py`（BM25 + RRF），`pipeline.retrieve()` 负责编排。

```
query
 ├─→ 向量检索 top-20 ─┐
 ├─→ BM25 检索 top-20 ┴→ RRF 融合 top-20 → Cross-Encoder 重排 top-4 → LLM
```

为什么加 BM25：向量对字面不敏感，查「ERR_4021 报错」「bge-m3 维度」这类精确串时，关键词检索完胜。本项目的 BM25 是**纯 stdlib 实现**（中文按二字词组 bigram 分词，零依赖）；生产可换 jieba 分词，或直接用 ES/Qdrant/Milvus 内置的 BM25/混合检索。

**RRF（Reciprocal Rank Fusion）**：`score = Σ 1/(k + rank)`（k=60）。只融合**排名**不融合原始分数 → 免去余弦与 BM25 的量纲归一化，是混合检索最常用的无参方法。

切换方式：

```bash
# .env
RETRIEVAL_MODE=hybrid   # 默认：混合
RETRIEVAL_MODE=vector   # 退回纯向量（对照实验用）

# 代码
RAGPipeline(...)  # pipeline.retrieval_mode 读环境变量
```

BM25 索引在 `build_index`/`load_index` 时由已入库 chunk 文本秒级重建，**不需要改索引产物、不需要重新向量化**——已有 `index/` 目录直接切 hybrid 即可。


为什么加 BM25：向量对字面不敏感，查「ERR_4021 报错」「bge-m3 维度」这类精确串时，关键词检索完胜。

## 检索质量评估（不做评估 = 盲调）

准备 30~50 条 **(问题, 应命中的文档)** 测试对，指标：

- **Hit Rate@k**：正确文档是否出现在 top-k（召回阶段看 @20，重排后看 @4）
- **MRR**：正确答案排在第几位（越靠前越高）
- **答案相关性**：用 LLM-as-Judge 对生成结果打分

改任何参数（chunk_size、模型、top_k）都跑一遍，否则调参就是玄学。

## 下一步

[05 · 生成与 Prompt](05-generation.md)
