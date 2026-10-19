"""向量存储：统一接口 + 可切换后端（factory 模式）。

接口契约（新增后端只需实现这 4 个方法）：
    build(vectors, chunks)   内存建索引
    search(query_vec, k)     返回 [(chunk, 余弦分数)]，降序
    save(path) / load(path)  持久化 / 恢复

切换方式（.env 或环境变量）：
    VECTOR_STORE=faiss     默认。精确暴力检索，百万级以内毫秒返回
    VECTOR_STORE=sqlite    stdlib 实现，零额外依赖，向量+文本单文件、可 SQL 过滤

生产扩展（实现同一接口即可接入，见 docs/06）：
    pgvector（已有 PostgreSQL，首选）/ Qdrant / Milvus（亿级分布式）/ Elasticsearch
"""
from __future__ import annotations

import json
import os
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np

from .chunker import Chunk


class VectorStore(ABC):
    """所有向量库后端的最小契约。"""

    @abstractmethod
    def build(self, vectors: np.ndarray, chunks: list[Chunk]) -> None: ...

    @abstractmethod
    def search(self, query_vec: np.ndarray, top_k: int = 10) -> list[tuple[Chunk, float]]:
        """返回 [(chunk, score)]，score 为余弦相似度 [-1, 1]，按分数降序。"""

    @abstractmethod
    def save(self, path: str | Path) -> None: ...

    @classmethod
    @abstractmethod
    def load(cls, path: str | Path) -> "VectorStore": ...


def _topk(scores: np.ndarray, ids: np.ndarray, chunks: list[Chunk]) -> list[tuple[Chunk, float]]:
    out = []
    for score, idx in zip(scores, ids):
        if idx < 0:  # FAISS 用 -1 表示不足 top_k
            continue
        out.append((chunks[int(idx)], float(score)))
    return out


class FaissVectorStore(VectorStore):
    """FAISS 内积索引（向量已归一化 → 内积 == 余弦相似度）。"""

    def __init__(self, dim: int | None = None):
        self.dim = dim
        self.index = None
        self.chunks: list[Chunk] = []

    def build(self, vectors: np.ndarray, chunks: list[Chunk]) -> None:
        import faiss

        assert vectors.shape[0] == len(chunks)
        self.dim = vectors.shape[1]
        self.index = faiss.IndexFlatIP(self.dim)
        self.index.add(vectors.astype("float32"))
        self.chunks = chunks

    def search(self, query_vec: np.ndarray, top_k: int = 10) -> list[tuple[Chunk, float]]:
        assert self.index is not None, "索引未构建或未加载"
        scores, ids = self.index.search(query_vec.reshape(1, -1).astype("float32"), top_k)
        return _topk(scores[0], ids[0], self.chunks)

    def save(self, path: str | Path) -> None:
        import faiss

        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(path / "index.faiss"))
        meta = [
            {"doc_id": c.doc_id, "chunk_id": c.chunk_id, "text": c.text, "metadata": c.metadata}
            for c in self.chunks
        ]
        (path / "chunks.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (path / "dim.txt").write_text(str(self.dim), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "FaissVectorStore":
        import faiss

        path = Path(path)
        store = cls(dim=int((path / "dim.txt").read_text()))
        store.index = faiss.read_index(str(path / "index.faiss"))
        store.chunks = [
            Chunk(
                doc_id=m["doc_id"],
                chunk_id=m["chunk_id"],
                text=m["text"],
                metadata=m["metadata"],
            )
            for m in json.loads((path / "chunks.json").read_text(encoding="utf-8"))
        ]
        return store


class SqliteVectorStore(VectorStore):
    """SQLite 单文件存储：向量 BLOB + 文本 + 元数据同库。

    检索时向量读入内存做精确内积（与 FAISS IndexFlatIP 完全同结果）。
    优点：零依赖、单文件易备份、可用 SQL 做 doc_id/租户过滤；
    适合百万级以内。生产换成 pgvector 即同一套 SQL 思路的分布式版。
    """

    TABLE = """CREATE TABLE IF NOT EXISTS chunks (
        chunk_id TEXT PRIMARY KEY,
        doc_id   TEXT NOT NULL,
        text     TEXT NOT NULL,
        metadata TEXT NOT NULL,
        embedding BLOB NOT NULL
    )"""

    def __init__(self, dim: int | None = None):
        self.dim = dim
        self.chunks: list[Chunk] = []
        self.vectors: np.ndarray | None = None  # 检索用内存副本

    def build(self, vectors: np.ndarray, chunks: list[Chunk]) -> None:
        assert vectors.shape[0] == len(chunks)
        self.dim = vectors.shape[1]
        self.vectors = vectors.astype("float32")
        self.chunks = chunks

    def search(self, query_vec: np.ndarray, top_k: int = 10) -> list[tuple[Chunk, float]]:
        assert self.vectors is not None, "索引未构建或未加载"
        # 向量已归一化 → 内积即余弦；行矩阵乘法等价逐条算内积
        scores = (self.vectors @ query_vec.astype("float32").reshape(-1))  # (n,)
        top = np.argsort(-scores)[:top_k]
        return [(self.chunks[int(i)], float(scores[i])) for i in top]

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        db = path / "vectors.db"
        if db.exists():
            db.unlink()  # 全量重建语义：旧数据直接覆盖
        conn = sqlite3.connect(db)
        try:
            conn.execute(self.TABLE)
            conn.executemany(
                "INSERT INTO chunks (chunk_id, doc_id, text, metadata, embedding) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (c.chunk_id, c.doc_id, c.text,
                     json.dumps(c.metadata, ensure_ascii=False),
                     self.vectors[i].tobytes())
                    for i, c in enumerate(self.chunks)
                ],
            )
            conn.commit()
        finally:
            conn.close()

    @classmethod
    def load(cls, path: str | Path) -> "SqliteVectorStore":
        db = Path(path) / "vectors.db"
        if not db.exists():
            raise FileNotFoundError(f"SQLite 索引不存在: {db}，请先运行 01_build_index.py")
        conn = sqlite3.connect(db)
        try:
            rows = conn.execute(
                "SELECT chunk_id, doc_id, text, metadata, embedding FROM chunks "
                "ORDER BY chunk_id"
            ).fetchall()
        finally:
            conn.close()
        store = cls()
        store.chunks = [
            Chunk(doc_id=r[1], chunk_id=r[0], text=r[2], metadata=json.loads(r[3]))
            for r in rows
        ]
        store.vectors = np.stack(
            [np.frombuffer(r[4], dtype="float32") for r in rows]
        ) if rows else np.zeros((0, 0), dtype="float32")
        store.dim = store.vectors.shape[1] if rows else None
        return store


# 后端注册表：新增 pgvector / milvus / qdrant 时在字典里登记一行即可
STORE_BACKENDS: dict[str, type[VectorStore]] = {
    "faiss": FaissVectorStore,
    "sqlite": SqliteVectorStore,
}


def build_vector_store(name: str | None = None) -> VectorStore:
    name = (name or os.getenv("VECTOR_STORE", "faiss")).lower()
    if name not in STORE_BACKENDS:
        raise ValueError(f"未知向量库后端: {name}，可选 {sorted(STORE_BACKENDS)}")
    return STORE_BACKENDS[name]()


def store_exists(path: str | Path, name: str | None = None) -> bool:
    """该后端的持久化产物是否已存在（pipeline.load_index 判断用）。"""
    name = (name or os.getenv("VECTOR_STORE", "faiss")).lower()
    path = Path(path)
    marker = {"faiss": "index.faiss", "sqlite": "vectors.db"}.get(name)
    if marker is None:
        return path.exists()
    return (path / marker).exists()


DEFAULT_INDEX_DIR = Path(os.getenv("INDEX_DIR", "index"))
