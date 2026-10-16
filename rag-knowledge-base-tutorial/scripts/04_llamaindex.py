"""框架写法 ①：LlamaIndex（生产 RAG 的主流选择）。

同样功能（加载 → 分块 → 向量化 → 建索引 → 混合召回 → 重排 → 生成），
原生版 ~400 行，这里 ~180 行 —— 框架把最佳实践封装成了组件。

用法：
    python scripts/04_llamaindex.py "你的问题"
    python scripts/04_llamaindex.py --strategy markdown "你的问题"

分块策略（与原生版 CHUNK_STRATEGY 同名，对应关系见 docs/07）：
    recursive（默认）→ SentenceSplitter     段落→句子递归打包（token 单位）
    markdown         → MarkdownNodeParser   按 # 标题结构切，忽略 chunk_size
    sentence         → SentenceSplitter     纯句子聚合（不按段落分组）

召回模式（RETRIEVAL_MODE，默认 hybrid）：
    hybrid → 向量 + 自定义 BM25NodeRetriever → QueryFusionRetriever(RRF)
    vector → 仅向量

向量库（VECTOR_STORE，与原生版同名但取值属于 LlamaIndex 生态）：
    simple（默认）→ 内置 SimpleVectorStore（dict 存储，零依赖）
    faiss         → llama-index-vector-stores-faiss（需额外安装，单机大规模）
    生产 → pgvector / Qdrant / Milvus（同接口，见 docs/06）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os

from llama_index.core import Settings, SimpleDirectoryReader, VectorStoreIndex
from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.response_synthesizers import get_response_synthesizer
from llama_index.core.retrievers import BaseRetriever, QueryFusionRetriever
from llama_index.core.schema import NodeWithScore, TextNode
from llama_index.llms.openai_like import OpenAILike

from rag.chunker import Chunk
from rag.retriever import BM25Index

DATA_DIR = Path(__file__).parent.parent / "data"
CACHE_ROOT = Path(__file__).parent.parent / "index_llamaindex"
CHUNK_SIZE = 512     # 注意：LlamaIndex 单位是 token（原生版是字符），中文 1 token ≈ 1~1.5 字
CHUNK_OVERLAP = 64
STRATEGIES = ("recursive", "markdown", "sentence")
RETRIEVAL_MODE = os.getenv("RETRIEVAL_MODE", "hybrid").lower()   # hybrid | vector
VECTOR_STORE = os.getenv("VECTOR_STORE", "simple").lower()       # simple | faiss

# ① LLM 全局配置（对应原生版 rag/llm.py）。Embedding 延迟到 ensure_settings()，
#    便于离线测试时用 MockEmbedding 注入。
Settings.llm = OpenAILike(
    model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
    api_base=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    api_key=os.getenv("OPENAI_API_KEY", "sk-..."),
    temperature=0.2,
    is_chat_model=True,
)


def ensure_settings() -> None:
    """设置 Embedding（本地 bge 模型，对应原生版 embedder.py 的 LocalEmbedder）。"""
    if getattr(Settings, "_embed_model", None) is not None:
        return  # 已注入（如离线测试用 MockEmbedding）
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding

    Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-zh-v1.5")


def build_parser(strategy: str):
    """分块策略 → LlamaIndex NodeParser（对应原生版 rag/chunker.py 的 STRATEGIES）。"""
    if strategy == "markdown":
        # 按标题结构切；框架版与原生版的差异：不保证 chunk_size，超长章节整块保留
        return MarkdownNodeParser()
    if strategy == "sentence":
        # paragraph_separator 给一个永不匹配的值 → 跳过段落分组，纯句子聚合
        return SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP,
                                paragraph_separator="\x00")
    if strategy == "recursive":
        return SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP,
                                paragraph_separator="\n\n")
    raise ValueError(f"未知分块策略: {strategy}，可选 {STRATEGIES}")


class BM25NodeRetriever(BaseRetriever):
    """自定义 LlamaIndex Retriever：内部复用原生版 rag/retriever.py 的 BM25Index。

    框架生态里没有开箱即用的中文 BM25（KeywordTableRetriever 要 LLM 抽词、费 token），
    这个适配层演示"自定义组件接进框架"的标准姿势。
    """

    def __init__(self, nodes: list, top_k: int = 20, **kw):
        super().__init__(**kw)
        self._top_k = top_k
        self._id2node = {n.id_: n for n in nodes}
        bm25_chunks = [
            Chunk(doc_id=n.metadata.get("doc_id", "doc"), chunk_id=n.id_,
                  text=n.text, metadata=dict(n.metadata))
            for n in nodes
        ]
        self._bm25 = BM25Index()
        self._bm25.build(bm25_chunks)

    def _retrieve(self, query_bundle) -> list[NodeWithScore]:
        hits = self._bm25.search(query_bundle.query_str, top_k=self._top_k)
        return [NodeWithScore(node=self._id2node[c.chunk_id], score=s) for c, s in hits]


# ---------- 向量库后端（VECTOR_STORE 切换）----------

def _faiss_backend(dim: int):
    try:
        import faiss
        from llama_index.vector_stores.faiss import FaissVectorStore as LIFaiss
    except ImportError as e:
        raise ImportError(
            "VECTOR_STORE=faiss 需要: pip install llama-index-vector-stores-faiss faiss-cpu"
        ) from e
    return LIFaiss(faiss_index=faiss.IndexFlatIP(dim))


def _load_index(cache_dir: Path):
    if VECTOR_STORE == "faiss":
        import faiss
        from llama_index.vector_stores.faiss import FaissVectorStore as LIFaiss

        vec_store = LIFaiss(faiss_index=faiss.read_index(str(cache_dir / "faiss.idx")))
        from llama_index.core import StorageContext, load_index_from_storage

        sc = StorageContext.from_defaults(vector_store=vec_store,
                                          persist_dir=str(cache_dir / "store"))
        return load_index_from_storage(sc)
    if VECTOR_STORE == "simple":
        from llama_index.core import StorageContext, load_index_from_storage

        return load_index_from_storage(
            StorageContext.from_defaults(persist_dir=str(cache_dir / "store")))
    raise ValueError(f"未知向量库: {VECTOR_STORE}，可选 simple | faiss"
                     "（sqlite 属于原生版/pgvector 生态，LlamaIndex 请用 pgvector）")


def build_or_load_index(strategy: str) -> VectorStoreIndex:
    """离线建库 → 按（策略 × 向量库）分别缓存；已存在则直接加载。"""
    cache_dir = CACHE_ROOT / strategy / VECTOR_STORE
    if (cache_dir / "store").exists():
        print(f"加载已有索引: {cache_dir}（store={VECTOR_STORE}）")
        return _load_index(cache_dir)

    # 加载 + 分块 + 向量化一步完成；显式传入策略对应的 parser
    parser = build_parser(strategy)
    docs = SimpleDirectoryReader(str(DATA_DIR), required_exts=[".md", ".txt"]).load_data()

    if VECTOR_STORE == "simple":
        # 默认后端：SimpleVectorStore（内存 dict），storage_context.persist 落 JSON
        index = VectorStoreIndex.from_documents(
            docs, transformations=[parser], show_progress=True)
    elif VECTOR_STORE == "faiss":
        dim = len(Settings.embed_model.get_text_embedding("probe"))
        backend = _faiss_backend(dim)
        index = VectorStoreIndex.from_documents(
            docs, transformations=[parser],
            storage_context=StorageContext_from(backend), show_progress=True)
    else:
        return _load_index(cache_dir)  # 触发 ValueError

    index.storage_context.persist(persist_dir=str(cache_dir / "store"))
    if VECTOR_STORE == "faiss":
        # FAISS 向量文件与 docstore 文本分开持久化（load 时两者都要读）
        index.vector_store.persist(str(cache_dir / "faiss.idx"))
    print(f"索引已构建并缓存: {cache_dir}（strategy={strategy}, store={VECTOR_STORE}）")
    return index


def StorageContext_from(backend):
    from llama_index.core import StorageContext

    return StorageContext.from_defaults(vector_store=backend)


def load_all_nodes(strategy: str) -> list:
    """用同一套 parser 重新切出 nodes，供 BM25 侧建索引（缓存命中时也要，纯本地计算）。"""
    docs = SimpleDirectoryReader(str(DATA_DIR), required_exts=[".md", ".txt"]).load_data()
    return build_parser(strategy).get_nodes_from_documents(docs)


def build_query_engine(index: VectorStoreIndex, strategy: str):
    """召回 + 重排 + 生成。RETRIEVAL_MODE=hybrid 时接入 QueryFusionRetriever（RRF）。"""
    try:
        from llama_index.postprocessor.sbert_rerank import SentenceTransformerRerank

        rerank = [SentenceTransformerRerank(model="BAAI/bge-reranker-base", top_n=4)]
    except Exception as e:  # 重排依赖未装则跳过，链路其余部分不变
        print(f"（重排模块不可用，跳过：{e}）")
        rerank = None

    if RETRIEVAL_MODE == "vector":
        return index.as_query_engine(
            similarity_top_k=20, node_postprocessors=rerank, streaming=True)

    if RETRIEVAL_MODE != "hybrid":
        raise ValueError(f"未知召回模式: {RETRIEVAL_MODE}，可选 hybrid | vector")

    # 混合：向量检索 + 自定义 BM25 → RRF 融合（reciprocal_rerank == RRF）
    vector_retriever = index.as_retriever(similarity_top_k=20)
    bm25_retriever = BM25NodeRetriever(load_all_nodes(strategy), top_k=20)
    fusion = QueryFusionRetriever(
        [vector_retriever, bm25_retriever],
        similarity_top_k=20,
        num_queries=1,              # =1 时不调 LLM 改写查询
        mode="reciprocal_rerank",   # LlamaIndex 里的 RRF
        use_async=False,
    )
    synthesizer = get_response_synthesizer(streaming=True)
    return RetrieverQueryEngine(
        retriever=fusion, response_synthesizer=synthesizer, node_postprocessors=rerank
    )


def main() -> None:
    args = sys.argv[1:]
    strategy = os.getenv("CHUNK_STRATEGY", "recursive")
    if "--strategy" in args:
        i = args.index("--strategy")
        strategy = args[i + 1]
        del args[i : i + 2]
    if not args:
        print('用法: python scripts/04_llamaindex.py '
              '[--strategy recursive|markdown|sentence] "你的问题"')
        return
    question = args[0]

    ensure_settings()
    index = build_or_load_index(strategy)

    # ② 检索 + 重排 + 生成（RETRIEVAL_MODE=hybrid 时：向量+BM25 → RRF 融合）
    print(f"召回模式: {RETRIEVAL_MODE}，向量库: {VECTOR_STORE}")
    query_engine = build_query_engine(index, strategy)

    print("=" * 60)
    response = query_engine.query(question)
    print("\n【回答】")
    for token in response.response_gen:
        print(token, end="", flush=True)
    print()

    # ③ 引用溯源：LlamaIndex 自带 source_nodes
    print("\n【引用来源】")
    for n in response.source_nodes:
        print(f"  score={n.score:.4f}  {n.node.get_content()[:60]}...")


if __name__ == "__main__":
    main()
