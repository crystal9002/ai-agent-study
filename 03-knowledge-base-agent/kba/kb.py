"""精简 RAG 检索层：把 01 教程的 chunker/embedder/vector_store/retriever 压成
~200 行、接口极简的模块，供 Agent 当作工具调用。对外只有两个函数：
    build_index(data_dir)  离线：扫 md → 分块 → 本地 bge 向量化 → FAISS + BM25
    search(query, k)       在线：向量 + BM25 混合召回（RRF 融合）→ top-k 条结果
与 01 教程的取舍（教学精简，生产见 docs/05）：分块只做标题感知；省掉 CrossEncoder
重排（候选少、收益低还拖慢响应）；BM25 纯 Python，加载时由文本重建、不落盘。"""
from __future__ import annotations
import json, math, os, re, threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# HuggingFace 官方源部分网络不通 → 切镜像；模型已在本机缓存 → 强制离线避免卡启动
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
# 本机坑（Intel Mac 实测）：faiss 的 BLAS 与 torch 的 OpenMP 共存且 faiss 先导入时，
# 模型首次前向段错误（exit 139）；限单线程即稳定，本教程规模下性能无感。
os.environ.setdefault("OMP_NUM_THREADS", "1")
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INDEX_DIR = ROOT / "index"
EMBED_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章：\n"  # bge 查询侧指令前缀

# 共享资源锁：LangGraph 会**并行**执行同一批工具，两个 search_kb 同时初始化
# SentenceTransformer 会竞争抛 "Cannot copy out of meta tensor"；一把可重入锁兜住。
_LOCK = threading.RLock()


@dataclass
class Chunk:
    chunk_id: str   # 全局唯一，如 "pricing_faq#0"
    doc_id: str     # 来源文件名（不含扩展名），引用溯源用
    title: str      # 所属章节标题
    text: str


# ---------- 1. 分块（Markdown 标题感知） ----------

def _split_long(text: str, max_chars: int) -> list[str]:
    """超长章节按中文句末标点二次切分。"""
    if len(text) <= max_chars:
        return [text]
    out, buf = [], ""
    for s in re.split(r"(?<=[。！？!?.\n])", text):
        if buf and len(buf) + len(s) > max_chars:
            out.append(buf.strip())
            buf = ""
        buf += s
    return out + ([buf.strip()] if buf.strip() else [])


def _has_content(lines: list[str]) -> bool:
    """缓冲里是否已有真正的正文行（排除标题行与空行）。"""
    return any(l.strip() and not re.match(r"^#{1,4}\s", l) for l in lines)


def _sections(text: str) -> list[tuple[str, str]]:
    """按 # 标题切出 (章节标题, 章节正文)；标题单独成行时并入下一节，避免"空标题块"。
    标题取章节内**最后一级**标题（叶子小节），比文档大标题更贴合引用溯源。"""
    parts: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
        if re.match(r"^#{1,4}\s", line) and _has_content(buf):
            parts.append("\n".join(buf).strip())
            buf = []
        buf.append(line)
    if buf:
        parts.append("\n".join(buf).strip())
    out: list[tuple[str, str]] = []
    for sec in (s for s in parts if s):
        heads = [l for l in sec.splitlines() if re.match(r"^#{1,4}\s", l)]
        title = re.sub(r"^#{1,4}\s+", "", heads[-1]) if heads else sec[:30]
        if len(sec) < 60 and out:
            out[-1] = (out[-1][0], out[-1][1] + "\n" + sec)   # 无正文的小块并入前块
        else:
            out.append((title, sec))
    return out


def chunk_markdown(text: str, doc_id: str, chunk_size: int = 400, overlap: int = 60) -> list[Chunk]:
    """标题感知分块：章节为单位，超长章节按句子补切并留 overlap 窗口缓解边界截断。"""
    chunks: list[Chunk] = []
    for title, body in _sections(text):
        for i, piece in enumerate(_split_long(body, chunk_size)):
            if i > 0 and overlap:
                piece = chunks[-1].text[-overlap:] + piece
            chunks.append(Chunk(f"{doc_id}#{len(chunks)}", doc_id, title, piece))
    return chunks


# ---------- 2. BM25（纯 Python，加载时由 chunk 文本重建） ----------

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+|[一-鿿]+")


def tokenize(text: str) -> list[str]:
    """英文/数字按单词、中文按二字词组（bigram）——零依赖的实用近似。"""
    toks: list[str] = []
    for m in _TOKEN_RE.finditer(text.lower()):
        tok = m.group()
        toks += ([tok] if tok[0].isascii() or len(tok) == 1
                 else [tok[i:i + 2] for i in range(len(tok) - 1)])
    return toks


class BM25Index:
    """BM25 Okapi（k1=1.5, b=0.75），教学规模（万级以内）够用。"""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b, self.avgdl = k1, b, 0.0
        self.tfs: list[Counter] = []
        self.lens: list[int] = []
        self.idf: dict[str, float] = {}

    def build(self, chunks: list[Chunk]) -> None:
        self.tfs = [Counter(tokenize(c.text)) for c in chunks]
        self.lens = [sum(tf.values()) for tf in self.tfs]
        self.avgdl = (sum(self.lens) / len(self.lens)) if chunks else 0.0
        n = len(chunks)
        df = Counter(tok for tf in self.tfs for tok in set(tf))   # 文档频率
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def search(self, query: str, top_k: int = 20) -> list[tuple[int, float]]:
        """返回 [(chunk 下标, BM25 分数)]，只保留命中（分数>0）的。"""
        scores = np.zeros(len(self.tfs), dtype="float64")
        for qt in tokenize(query):
            idf = self.idf.get(qt)
            if idf is None:
                continue
            for i, tf in enumerate(self.tfs):
                f = tf.get(qt, 0)
                if f:
                    scores[i] += idf * (f * (self.k1 + 1)) / (
                        f + self.k1 * (1 - self.b + self.b * self.lens[i] / self.avgdl))
        top = np.argsort(-scores)[:top_k]
        return [(int(i), float(scores[int(i)])) for i in top if scores[int(i)] > 0]


def rrf_fuse(*ranked: list[tuple[int, float]], k: int = 60) -> list[tuple[int, float]]:
    """RRF 融合：score = Σ 1/(k + rank)，只看排名不看分数 → 免去量纲归一化
    （k=60 为论文推荐值）。"""
    fused: dict[int, float] = {}
    for lst in ranked:
        for rank, (idx, _) in enumerate(lst, start=1):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank)
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)


# ---------- 3. 知识库：离线建库 + 在线检索 ----------

class KnowledgeBase:
    def __init__(self) -> None:
        self.chunks: list[Chunk] = []
        self.index = None                  # faiss 索引，首次检索时懒加载
        self.bm25: BM25Index | None = None
        self._model = None  # SentenceTransformer 懒加载

    def _embed(self, texts: list[str], is_query: bool = False) -> np.ndarray:
        """本地 bge 向量化；已归一化 → FAISS 内积等价余弦相似度。加锁串行化，
        防止并行工具调用同时构造模型（详见 _LOCK 注释）。"""
        with _LOCK:
            if self._model is None:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(EMBED_MODEL, device="cpu")
            if is_query:
                texts = [QUERY_PREFIX + t for t in texts]
            return np.asarray(self._model.encode(texts, normalize_embeddings=True,
                                                  show_progress_bar=False), dtype="float32")

    def build_index(self, data_dir: str | Path, index_dir: str | Path = DEFAULT_INDEX_DIR) -> int:
        """扫描目录下 .md → 分块 → 向量化 → FAISS + BM25，落盘到 index_dir，返回 chunk 数。"""
        import faiss
        data_dir, index_dir = Path(data_dir), Path(index_dir)
        chunks: list[Chunk] = []
        for p in sorted(data_dir.rglob("*.md")):
            doc_chunks = chunk_markdown(p.read_text(encoding="utf-8"), doc_id=p.stem)
            chunks.extend(doc_chunks)
            print(f"  加载 {p.relative_to(data_dir)} → {len(doc_chunks)} 块")
        if not chunks:
            raise FileNotFoundError(f"{data_dir} 下没有 .md 文档，无法建库")
        vectors = self._embed([c.text for c in chunks])
        self.chunks = chunks
        self.index = faiss.IndexFlatIP(vectors.shape[1])
        self.index.add(vectors)
        self.bm25 = BM25Index()
        self.bm25.build(chunks)
        index_dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(index_dir / "index.faiss"))
        (index_dir / "chunks.json").write_text(
            json.dumps([c.__dict__ for c in chunks], ensure_ascii=False, indent=2), encoding="utf-8")
        return len(chunks)

    def load_index(self, index_dir: str | Path = DEFAULT_INDEX_DIR) -> None:
        import faiss
        index_dir = Path(index_dir)
        if not (index_dir / "index.faiss").exists():
            raise FileNotFoundError(f"索引不存在: {index_dir}，请先运行 scripts/01_build_kb.py")
        self.index = faiss.read_index(str(index_dir / "index.faiss"))
        self.chunks = [Chunk(**m) for m in json.loads(
            (index_dir / "chunks.json").read_text(encoding="utf-8"))]
        self.bm25 = BM25Index()
        self.bm25.build(self.chunks)       # 由文本秒级重建，无需落盘

    def search(self, query: str, k: int = 3) -> list[dict]:
        """混合召回 top-k，返回带序号 n 的结果（n 即回答里的引用编号 [n]）。"""
        if self.index is None:              # 双检锁：并行首查只加载一次索引
            with _LOCK:
                if self.index is None:
                    self.load_index()
        # faiss.search 返回 (相似度, 索引) 两组数组，顺序别搞反
        sims, ids = self.index.search(self._embed([query], is_query=True), 20)
        vec_hits = [(int(i), float(d)) for d, i in zip(sims[0], ids[0]) if i >= 0]
        fused = rrf_fuse(vec_hits, self.bm25.search(query, top_k=20))[: max(k, 1)]
        return [{"n": r, "doc": self.chunks[i].doc_id, "title": self.chunks[i].title,
                 "text": self.chunks[i].text, "score": round(s, 4)}
                for r, (i, s) in enumerate(fused, start=1)]


# ---------- 4. 模块级极简接口（工具层只用这两个） ----------

_KB: KnowledgeBase | None = None


def build_index(data_dir: str | Path, index_dir: str | Path = DEFAULT_INDEX_DIR) -> int:
    """离线建库，返回 chunk 总数。"""
    global _KB
    _KB = KnowledgeBase()
    return _KB.build_index(data_dir, index_dir)


def search(query: str, k: int = 3) -> list[dict]:
    """在线检索；索引不存在时抛 FileNotFoundError，由工具层转成结构化错误回填。"""
    global _KB
    if _KB is None:
        with _LOCK:                       # 并行首查只初始化一个单例
            if _KB is None:
                _KB = KnowledgeBase()
                _KB.load_index()
    return _KB.search(query, k)
