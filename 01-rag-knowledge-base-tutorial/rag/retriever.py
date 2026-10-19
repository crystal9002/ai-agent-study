"""混合召回：向量检索 + BM25 关键词检索 → RRF 融合。

为什么需要混合：
- 向量检索擅长语义（"怎么退款" ↔ "退款流程"），但对**精确串不敏感**
  （型号 "XH-3000"、错误码 "ERR_4021"、数字表格）
- BM25 恰好相反：字面精确匹配强，语义泛化弱
- 两者互补，是生产 RAG 的标配召回方案

链路（pipeline.retrieve）：
  query ──向量──→ vec_hits(top_k)
       └─BM25──→ bm25_hits(top_k)
                    ↓ RRF 融合（按排名而不是分数合并，免去归一化）
                 fused(top_k) ──重排──→ top_n
"""
from __future__ import annotations

import math
import re
from collections import Counter

import numpy as np

from .chunker import Chunk

# 中文按"二字词组"切分（bigram），英文/数字按单词——零依赖的实用近似。
# 生产中文分词效果更好：jieba /.pkuseg；多语言场景可换 bge-m3 的 token 粒度。
_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+|[一-鿿]+")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for m in _TOKEN_RE.finditer(text.lower()):
        tok = m.group()
        if tok[0].isascii() or len(tok) == 1:
            tokens.append(tok)
        else:
            tokens.extend(tok[i : i + 2] for i in range(len(tok) - 1))
    return tokens


class BM25Index:
    """BM25 Okapi（k1=1.5, b=0.75）。纯 Python，适合百万级以内教学/中小规模。"""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.chunks: list[Chunk] = []
        self.doc_tfs: list[Counter] = []
        self.doc_lens: list[int] = []
        self.avgdl: float = 0.0
        self.idf: Counter = Counter()

    def build(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self.doc_tfs = [Counter(tokenize(c.text)) for c in chunks]
        self.doc_lens = [sum(tf.values()) for tf in self.doc_tfs]
        self.avgdl = (sum(self.doc_lens) / len(self.doc_lens)) if chunks else 0.0
        # idf：平滑版 BM25 Okapi
        n = len(chunks)
        df = Counter()
        for tf in self.doc_tfs:
            df.update(tf.keys())
        self.idf = Counter({
            t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()
        })

    def search(self, query: str, top_k: int = 10) -> list[tuple[Chunk, float]]:
        if not self.chunks:
            return []
        q_toks = tokenize(query)
        scores = np.zeros(len(self.chunks), dtype="float64")
        for qt in q_toks:
            idf = self.idf.get(qt)
            if idf is None:
                continue
            for i, tf in enumerate(self.doc_tfs):
                f = tf.get(qt, 0)
                if not f:
                    continue
                scores[i] += idf * (f * (self.k1 + 1)) / (
                    f + self.k1 * (1 - self.b + self.b * self.doc_lens[i] / self.avgdl)
                )
        top = np.argsort(-scores)[:top_k]
        # 只保留有命中（分数>0）的
        return [(self.chunks[int(i)], float(scores[int(i)])) for i in top if scores[int(i)] > 0]


def rrf_fuse(
    *ranked_lists: list[tuple[Chunk, float]],
    k: int = 60,
    top_k: int | None = None,
) -> list[tuple[Chunk, float]]:
    """Reciprocal Rank Fusion：score = Σ 1/(k + rank)，rank 从 1 开始。

    只看**排名**不看原始分数 → 免去向量余弦与 BM25 量纲归一化，
    是混合检索最常用的无参融合方式（k=60 为论文推荐值）。
    同一 chunk 出现在多个列表 → 分数累加（被多个信号同时认可）。
    """
    fused: dict[str, float] = {}
    chunk_by_id: dict[str, Chunk] = {}
    for ranked in ranked_lists:
        for rank, (chunk, _) in enumerate(ranked, start=1):
            fused[chunk.chunk_id] = fused.get(chunk.chunk_id, 0.0) + 1.0 / (k + rank)
            chunk_by_id[chunk.chunk_id] = chunk
    merged = sorted(fused.items(), key=lambda x: x[1], reverse=True)
    if top_k is not None:
        merged = merged[:top_k]
    return [(chunk_by_id[cid], score) for cid, score in merged]
