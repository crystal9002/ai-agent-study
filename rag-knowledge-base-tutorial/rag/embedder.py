"""Embedding 封装：本地模型 / OpenAI 兼容 API 二选一。

生产建议：
- 中文：BAAI/bge-m3（效果最好）、bge-large-zh-v1.5
- 追求速度：bge-small-zh-v1.5（本教程默认）
- 已有 API 体系：text-embedding-3-small / 通义 text-embedding-v3
"""
from __future__ import annotations

import os


class LocalEmbedder:
    """基于 sentence-transformers 的本地 Embedding。

    关键点：bge 系列要求查询前加指令前缀（instruction），文档侧不加，
    这样查询和文档落在同一语义空间。此处已自动处理。
    """

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5", device: str | None = None):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name, device=device)
        self.model_name = model_name
        self.is_query_prefix = "bge" in model_name.lower()

    def encode(self, texts: list[str], is_query: bool = False) -> "np.ndarray":
        import numpy as np

        if self.is_query_prefix and is_query:
            texts = [
                "为这个句子生成表示以用于检索相关文章：\n" + t for t in texts
            ]
        vecs = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vecs, dtype="float32")


class APIEmbedder:
    """OpenAI 兼容 API Embedding（可对接 OpenAI / DeepSeek / 通义 / 方舟等）。"""

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        base_url: str | None = None,
        api_key: str | None = None,
    ):
        from openai import OpenAI

        self.model = model
        self.client = OpenAI(
            base_url=base_url or os.getenv("EMBEDDING_BASE_URL") or os.getenv("OPENAI_BASE_URL"),
            api_key=api_key or os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY"),
        )

    def encode(self, texts: list[str], is_query: bool = False) -> "np.ndarray":
        import numpy as np

        # OpenAI API 单次上限 2048 条
        vecs: list[list[float]] = []
        for i in range(0, len(texts), 2048):
            resp = self.client.embeddings.create(model=self.model, input=texts[i : i + 2048])
            vecs.extend(d.embedding for d in resp.data)
        arr = np.asarray(vecs, dtype="float32")
        # 影响余弦相似度的只有方向，归一化后可用内积等价余弦
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        return arr / np.clip(norms, 1e-12, None)


def build_embedder() -> LocalEmbedder | APIEmbedder:
    """按环境变量选择 embedder：EMBEDDING_PROVIDER=api 时走 API，否则本地。"""
    if os.getenv("EMBEDDING_PROVIDER", "local") == "api":
        return APIEmbedder(model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"))
    return LocalEmbedder(model_name=os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"))
