"""重排（Rerank）：召回阶段求"全"，重排阶段求"准"。

两段式检索是生产 RAG 标配：
1. 向量召回 top-50~100（高召回率，精度一般）
2. Cross-Encoder 重排取 top-3~5（把真正相关的提到最前面）

Cross-Encoder 把 query 和 doc 拼在一起过模型，比向量"双塔"相似度准得多，
但算力开销大，所以只能对少量候选做。
"""
from __future__ import annotations

import os


class CrossEncoderReranker:
    def __init__(self, model_name: str | None = None):
        from sentence_transformers import CrossEncoder

        model_name = model_name or os.getenv(
            "RERANK_MODEL", "BAAI/bge-reranker-base"
        )
        # 中文生产推荐 BAAI/bge-reranker-v2-m3（更大更准）
        self.model = CrossEncoder(model_name)
        self.model_name = model_name

    def rerank(self, query: str, docs: list[str], top_n: int = 5) -> list[tuple[int, float]]:
        """返回 [(候选原始下标, 相关性得分)]，按得分降序取 top_n。"""
        pairs = [(query, d) for d in docs]
        scores = self.model.predict(pairs)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        return [(i, float(s)) for i, s in ranked[:top_n]]


class NoopReranker:
    """跳过重排（调试用，或召回结果本来就少）。"""

    def rerank(self, query: str, docs: list[str], top_n: int = 5) -> list[tuple[int, float]]:
        return [(i, 0.0) for i in range(min(top_n, len(docs)))]


def build_reranker() -> CrossEncoderReranker | NoopReranker:
    if os.getenv("RERANK_ENABLED", "1") == "0":
        return NoopReranker()
    return CrossEncoderReranker()
