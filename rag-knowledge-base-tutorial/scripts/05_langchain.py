"""框架写法 ②：LangChain（通用 LLM 应用框架的对照实现）。

与原生版/LlamaIndex 版跑同一份 data/，方便横向对比三种写法。
混合召回（RETRIEVAL_MODE=hybrid，默认）：向量 + BM25 → RRF 融合，
BM25 与融合逻辑直接复用原生版 rag/retriever.py —— 框架间组件可互相借用。

向量库（VECTOR_STORE，与原生版同名，取值为 LangChain 生态）：
    faiss（默认）→ langchain FAISS
    sqlite       → 自定义 SQLiteVectorStore（LangChain VectorStore 接口适配，
                   内部复用原生 rag/vector_store.py::SqliteVectorStore）
    chroma       → Chroma 向量数据库（嵌入式 DB，langchain-chroma 官方集成）
    pgvector     → PostgreSQL + pgvector 扩展（服务端生产形态，langchain-postgres，
                   PG_CONN 指定连接串）

用法：
    python scripts/05_langchain.py "团队版多少钱，几个人可以用？"
    python scripts/05_langchain.py --strategy markdown "你的问题"
    VECTOR_STORE=sqlite python scripts/05_langchain.py "你的问题"
    VECTOR_STORE=chroma python scripts/05_langchain.py "你的问题"
    VECTOR_STORE=pgvector PG_CONN=postgresql+psycopg2://user:pass@host:5432/db \
        python scripts/05_langchain.py "你的问题"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os

import numpy as np
from langchain_community.document_loaders import TextLoader
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.vectorstores import VectorStore as LCVectorStore
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_openai import ChatOpenAI
from langchain_text_splitters import (MarkdownTextSplitter,
                                      RecursiveCharacterTextSplitter)

from rag.chunker import Chunk
from rag.retriever import BM25Index, rrf_fuse
from rag.vector_store import SqliteVectorStore

DATA_DIR = Path(__file__).parent.parent / "data"
CACHE_ROOT = Path(__file__).parent.parent / "index_langchain"
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64
STRATEGIES = ("recursive", "markdown", "sentence")
RETRIEVAL_MODE = os.getenv("RETRIEVAL_MODE", "hybrid").lower()   # hybrid | vector
VECTOR_STORE = os.getenv("VECTOR_STORE", "faiss").lower()        # faiss | sqlite | chroma | pgvector
PG_CONN = os.getenv("PG_CONN", "postgresql+psycopg2://rag:rag@localhost:5432/rag")

SYSTEM_PROMPT = """你是一个基于知识库的问答助手。规则：
1. 只根据【知识库资料】回答，不要编造资料中不存在的内容。
2. 回答时在关键句末尾标注来源编号，如 [1]、[2]。
3. 如果资料不足以回答，明确说"知识库中没有相关信息"。
4. 用简洁的中文回答。"""

PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        (
            "human",
            "【知识库资料】\n{context}\n\n【用户问题】\n{question}",
        ),
    ]
)


def get_embeddings() -> HuggingFaceEmbeddings:
    """对应原生版 embedder.py：本地 bge 模型，归一化向量。"""
    return HuggingFaceEmbeddings(
        model_name="BAAI/bge-small-zh-v1.5",
        encode_kwargs={"normalize_embeddings": True},
    )


class SQLiteVectorStore(LCVectorStore):
    """LangChain VectorStore 接口适配层：内部复用原生 SqliteVectorStore。

    演示"自定义后端接进框架"的最小面：from_texts（建库）+
    similarity_search_with_score（检索）+ save_local/load_local（持久化）。
    """

    def __init__(self, embedding, store: SqliteVectorStore | None = None):
        self.embedding = embedding
        self._store = store or SqliteVectorStore()

    @classmethod
    def from_texts(cls, texts, embedding, metadatas=None, **kwargs):
        metadatas = metadatas or [{}] * len(texts)
        vectors = np.asarray(embedding.embed_documents(list(texts)), dtype="float32")
        chunks = [
            Chunk(doc_id=str(m.get("source", "doc")), chunk_id=f"c{i}",
                  text=t, metadata=dict(m))
            for i, (t, m) in enumerate(zip(texts, metadatas))
        ]
        store = SqliteVectorStore()
        store.build(vectors, chunks)
        return cls(embedding, store)

    def similarity_search_with_score(self, query, k=4, **kwargs):
        qv = np.asarray(self.embedding.embed_query(query), dtype="float32")
        hits = self._store.search(qv, top_k=k)
        # 原生返回余弦相似度，LangChain 约定返回"越小越近"的距离 → 1 - cos
        return [(Document(page_content=c.text, metadata=c.metadata), 1.0 - score)
                for c, score in hits]

    def similarity_search(self, query, k=4, **kwargs):
        return [d for d, _ in self.similarity_search_with_score(query, k, **kwargs)]

    def add_texts(self, texts, metadatas=None, **kwargs):
        raise NotImplementedError("教程未实现增量添加；重建索引即可")

    # 自定义持久化（对齐 FAISS.save_local/load_local 的使用方式）
    def save_local(self, path: str) -> None:
        self._store.save(path)

    @classmethod
    def load_local(cls, path: str, embedding) -> "SQLiteVectorStore":
        return cls(embedding, SqliteVectorStore.load(path))


def build_splitter(strategy: str):
    """分块策略 → LangChain Splitter（对应原生版 rag/chunker.py 的 STRATEGIES）。"""
    if strategy == "markdown":
        # 按标题结构切；与原生版差异：不保证 chunk_size，超长章节整块保留
        return MarkdownTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    if strategy == "sentence":
        # 分隔符只留句子边界 → 纯句子聚合，不按段落分组
        return RecursiveCharacterTextSplitter(
            separators=["。", "！", "？", ". ", "! ", "? ", "\n"],
            chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP, keep_separator=True,
        )
    if strategy == "recursive":
        return RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    raise ValueError(f"未知分块策略: {strategy}，可选 {STRATEGIES}")


def build_or_load_store(strategy: str):
    """加载 → 分块 → 向量化 → 向量库（VECTOR_STORE=faiss|sqlite|chroma|pgvector，缓存按策略×后端隔离）。"""
    cache_dir = CACHE_ROOT / strategy / VECTOR_STORE
    embeddings = get_embeddings()

    if VECTOR_STORE == "faiss":
        if (cache_dir / "index.faiss").exists():
            print(f"加载已有索引: {cache_dir}（store=faiss）")
            return FAISS.load_local(str(cache_dir), embeddings,
                                    allow_dangerous_deserialization=True)
        chunks = load_all_documents(strategy)
        store = FAISS.from_documents(chunks, embeddings)
        store.save_local(str(cache_dir))
        print(f"索引已构建并缓存: {cache_dir}（strategy={strategy}, store=faiss, "
              f"{len(chunks)} 个 chunk）")
        return store

    if VECTOR_STORE == "sqlite":
        if (cache_dir / "vectors.db").exists():
            print(f"加载已有索引: {cache_dir}（store=sqlite）")
            return SQLiteVectorStore.load_local(str(cache_dir), embeddings)
        chunks = load_all_documents(strategy)
        store = SQLiteVectorStore.from_documents(chunks, embeddings)
        store.save_local(str(cache_dir))
        print(f"索引已构建并缓存: {cache_dir}（strategy={strategy}, store=sqlite, "
              f"{len(chunks)} 个 chunk）")
        return store

    if VECTOR_STORE == "chroma":
        # 嵌入式向量数据库：写入即落盘到 cache_dir，collection 内自带 doc 元数据
        from langchain_chroma import Chroma

        if (cache_dir / "chroma.sqlite3").exists():
            print(f"加载已有索引: {cache_dir}（store=chroma）")
            return Chroma(persist_directory=str(cache_dir),
                          embedding_function=embeddings, collection_name="docs")
        chunks = load_all_documents(strategy)
        store = Chroma.from_documents(chunks, embeddings,
                                      persist_directory=str(cache_dir),
                                      collection_name="docs")
        print(f"索引已构建并缓存: {cache_dir}（strategy={strategy}, store=chroma, "
              f"{len(chunks)} 个 chunk）")
        return store

    if VECTOR_STORE == "pgvector":
        # 服务端向量数据库：表/集合在 PG 里，本地缓存目录只放 .built 标记
        from langchain_postgres import PGVector

        if (cache_dir / ".built").exists():
            print(f"加载已有索引: {cache_dir}（store=pgvector）")
            return PGVector(embeddings, connection=PG_CONN,
                            collection_name=f"rag_{strategy}", use_jsonb=True)
        chunks = load_all_documents(strategy)
        # pre_delete_collection=True：重建前清空同名集合，避免重复写入
        store = PGVector.from_documents(chunks, embeddings, connection=PG_CONN,
                                        collection_name=f"rag_{strategy}",
                                        pre_delete_collection=True, use_jsonb=True)
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / ".built").touch()
        print(f"索引已构建并缓存: {cache_dir}（strategy={strategy}, store=pgvector, "
              f"{len(chunks)} 个 chunk）")
        return store

    raise ValueError(f"未知向量库: {VECTOR_STORE}，可选 faiss | sqlite | chroma | pgvector")


def load_all_documents(strategy: str) -> list:
    """用同一套 splitter 重新切出文档，供 BM25 侧建索引（缓存命中时也要，纯本地计算）。"""
    splitter = build_splitter(strategy)
    docs = []
    for p in sorted(DATA_DIR.rglob("*")):
        if p.suffix.lower() in {".md", ".txt"} and p.is_file():
            docs.extend(TextLoader(p, encoding="utf-8").load())
    return splitter.split_documents(docs)


def _as_chunk(d: Document) -> Chunk:
    """LangChain Document → 原生 Chunk（fusion 用 page_content 作 id，免跨对象映射）。"""
    return Chunk(
        doc_id=Path(d.metadata.get("source", "doc")).stem,
        chunk_id=d.page_content,
        text=d.page_content,
        metadata=dict(d.metadata),
    )


def retrieve(store: LCVectorStore, question: str, strategy: str, top_k: int = 20) -> list:
    """召回：vector=纯向量；hybrid=向量+BM25 → RRF（复用 rag/retriever.py）。"""
    if RETRIEVAL_MODE == "vector":
        return [d for d, _ in store.similarity_search_with_score(question, k=top_k)]
    if RETRIEVAL_MODE != "hybrid":
        raise ValueError(f"未知召回模式: {RETRIEVAL_MODE}，可选 hybrid | vector")

    # FAISS/Chroma 均返回 L2 距离（越小越近）→ 转成"越大越近"参与展示，RRF 只用排名
    vec_hits = [(_as_chunk(d), 1.0 / (1.0 + dist))
                for d, dist in store.similarity_search_with_score(question, k=top_k)]

    bm25 = BM25Index()
    bm25.build([_as_chunk(d) for d in load_all_documents(strategy)])

    fused = rrf_fuse(vec_hits, bm25.search(question, top_k=top_k), top_k=top_k)
    return [Document(page_content=c.text, metadata=c.metadata) for c, _ in fused]


def rerank(query: str, docs: list, top_n: int = 4) -> list:
    """Cross-Encoder 重排（对应原生版 rag/reranker.py，复用同一个依赖）。"""
    from sentence_transformers import CrossEncoder

    model = CrossEncoder(os.getenv("RERANK_MODEL", "BAAI/bge-reranker-base"))
    scores = model.predict([(query, d.page_content) for d in docs])
    ranked = sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)
    return [d for d, _ in ranked[:top_n]]


def format_docs(docs: list) -> str:
    return "\n\n".join(
        f"[{i + 1}]（来源：{Path(d.metadata.get('source', '?')).stem}）\n{d.page_content}"
        for i, d in enumerate(docs)
    )


def main() -> None:
    args = sys.argv[1:]
    strategy = os.getenv("CHUNK_STRATEGY", "recursive")
    if "--strategy" in args:
        i = args.index("--strategy")
        strategy = args[i + 1]
        del args[i : i + 2]
    if not args:
        print('用法: python scripts/05_langchain.py '
              '[--strategy recursive|markdown|sentence] "你的问题"')
        return
    question = args[0]
    store = build_or_load_store(strategy)

    # ① 混合召回 top-20 → 重排 top-4（对应原生版 pipeline.retrieve）
    print(f"召回模式: {RETRIEVAL_MODE}，向量库: {VECTOR_STORE}")
    candidates = retrieve(store, question, strategy)
    top_docs = rerank(question, candidates)
    print("=" * 60)
    print("【检索结果（重排后）】")
    for i, d in enumerate(top_docs, 1):
        print(f"  [{i}] {d.page_content[:60]}...")

    # ② LCEL 链：context 组装 → Prompt → LLM → 字符串输出
    chain = (
        {
            "context": lambda x: format_docs(top_docs),
            "question": RunnablePassthrough(),
        }
        | PROMPT
        | ChatOpenAI(
            model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            base_url=os.getenv("OPENAI_BASE_URL"),
            temperature=0.2,
        )
        | StrOutputParser()
    )

    print("\n【回答】")
    for token in chain.stream(question):
        print(token, end="", flush=True)
    print()


if __name__ == "__main__":
    main()
