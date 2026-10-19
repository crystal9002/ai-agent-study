"""端到端 RAG Pipeline：索引（离线） + 问答（在线）。

在线链路：
query → 改写/理解(可选) → Embedding → 向量召回 top-k
      → Cross-Encoder 重排 top-n → 构建 Prompt → LLM 生成（带引用）
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os

from .chunker import Chunk, chunk_text
from .embedder import build_embedder
from .llm import LLM
from .reranker import build_reranker
from .retriever import BM25Index, rrf_fuse
from .vector_store import (DEFAULT_INDEX_DIR, VectorStore, build_vector_store,
                           store_exists)

SYSTEM_PROMPT = """你是一个基于知识库的问答助手。规则：
1. 只根据【知识库资料】回答，不要编造资料中不存在的内容。
2. 回答时在关键句末尾标注来源编号，如 [1]、[2]。
3. 如果资料不足以回答，明确说"知识库中没有相关信息"，不要猜测。
4. 用简洁的中文回答。"""

USER_TEMPLATE = """【知识库资料】
{context}

【用户问题】
{question}"""


@dataclass
class RAGResult:
    answer: str
    contexts: list[Chunk] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)


class RAGPipeline:
    def __init__(
        self,
        top_k: int = 20,       # 向量召回数量
        top_n: int = 4,        # 重排后送入 LLM 的数量
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        chunk_strategy: str | None = None,   # recursive / markdown / sentence，None 读环境变量
    ):
        self.top_k = top_k
        self.top_n = top_n
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.chunk_strategy = chunk_strategy or os.getenv("CHUNK_STRATEGY", "recursive")
        self.store_name = os.getenv("VECTOR_STORE", "faiss").lower()
        self.retrieval_mode = os.getenv("RETRIEVAL_MODE", "hybrid").lower()
        self.embedder = build_embedder()
        self.reranker = build_reranker()
        self.store: VectorStore | None = None
        self.bm25: BM25Index | None = None

    # ---------- 离线：构建索引 ----------
    def build_index(self, documents: dict[str, str], index_dir=None) -> None:
        """documents: {doc_id: 全文}"""
        chunks: list[Chunk] = []
        for doc_id, text in documents.items():
            chunks.extend(
                chunk_text(text, doc_id=doc_id, chunk_size=self.chunk_size,
                           overlap=self.chunk_overlap, strategy=self.chunk_strategy)
            )
        vectors = self.embedder.encode([c.text for c in chunks])
        self.store = build_vector_store(self.store_name)
        self.store.build(vectors, chunks)
        self.bm25 = BM25Index()
        self.bm25.build(chunks)
        if index_dir is not None:
            self.store.save(index_dir)
        print(f"索引构建完成：{len(chunks)} 个 chunk"
              f"（strategy={self.chunk_strategy}, store={self.store_name}），"
              f"向量维度 {vectors.shape[1]}")

    def load_index(self, index_dir=DEFAULT_INDEX_DIR) -> None:
        if not store_exists(index_dir, self.store_name):
            raise FileNotFoundError(
                f"store={self.store_name} 的索引不存在: {index_dir}，"
                f"请先运行 scripts/01_build_index.py"
            )
        self.store = build_vector_store(self.store_name).load(index_dir)
        # BM25 由已入库的 chunk 文本重建（纯内存计算，秒级）
        self.bm25 = BM25Index()
        self.bm25.build(self.store.chunks)
        print(f"索引加载完成：{len(self.store.chunks)} 个 chunk（store={self.store_name}）")

    # ---------- 在线：检索 + 生成 ----------
    def retrieve(self, question: str) -> tuple[list[Chunk], list[float]]:
        """召回（向量 或 混合）→ RRF 融合 → 重排 top_n。"""
        assert self.store is not None and self.bm25 is not None, \
            "请先 build_index() 或 load_index()"
        q_vec = self.embedder.encode([question], is_query=True)

        if self.retrieval_mode == "hybrid":
            vec_hits = self.store.search(q_vec, top_k=self.top_k)
            bm25_hits = self.bm25.search(question, top_k=self.top_k)
            hits = rrf_fuse(vec_hits, bm25_hits, top_k=self.top_k)
        elif self.retrieval_mode == "vector":
            hits = self.store.search(q_vec, top_k=self.top_k)
        else:
            raise ValueError(
                f"未知召回模式: {self.retrieval_mode}，可选 hybrid | vector")

        # 重排作用在召回结果上（hybrid 模式下已含 BM25 补充的精确匹配）
        reranked = self.reranker.rerank(question, [c.text for c, _ in hits], top_n=self.top_n)
        return (
            [hits[i][0] for i, _ in reranked],
            [s for _, s in reranked],
        )

    @staticmethod
    def build_prompt(question: str, chunks: list[Chunk]) -> str:
        context = "\n\n".join(
            f"[{i + 1}]（来源：{c.doc_id}）\n{c.text}" for i, c in enumerate(chunks)
        )
        return USER_TEMPLATE.format(context=context, question=question)

    def query(self, question: str) -> RAGResult:
        chunks, _ = self.retrieve(question)
        prompt = self.build_prompt(question, chunks)
        llm = LLM()
        answer = llm.chat(SYSTEM_PROMPT, prompt)
        return RAGResult(answer=answer, contexts=chunks)

    def query_stream(self, question: str):
        """流式问答：先 yield 检索到的上下文，再逐字 yield 答案。"""
        chunks, _ = self.retrieve(question)
        prompt = self.build_prompt(question, chunks)
        yield ("context", chunks)
        for tok in LLM().chat_stream(SYSTEM_PROMPT, prompt):
            yield ("token", tok)
