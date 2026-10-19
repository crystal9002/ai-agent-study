"""第六步：Web 界面（FastAPI + SSE 流式问答）。

把 scripts/03_chat.py 的命令行问答搬到浏览器：
    GET /            单页前端（web/index.html，原生 HTML/JS，零框架）
    GET /api/config  当前配置（分块策略 / 召回模式 / 向量库 / chunk 数）
    GET /api/query   SSE 流：sources 事件（引用来源）→ token 事件（逐字）→ done

为什么用 SSE 而不是 WebSocket：问答是"服务端单向推送"，SSE 协议极简、
浏览器原生支持自动重连、HTTP 长连接即可——这正是生产网关最常用的流式方案。

用法：
    python scripts/06_web.py                 # http://127.0.0.1:8000
    PORT=9000 python scripts/06_web.py
    INDEX_DIR=... CHUNK_STRATEGY=... 与命令行版完全同源（.env / 环境变量）
首次启动若索引不存在会自动构建（本地 embedding 模型首次运行需下载）。
"""
import json
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
import uvicorn

from rag import RAGPipeline
from rag.vector_store import DEFAULT_INDEX_DIR

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
STATIC_DIR = ROOT / "web"
SUPPORTED = {".txt", ".md"}

app = FastAPI(title="RAG Knowledge Base Tutorial")

# ---------- Pipeline 单例（首次请求时惰性加载/构建，之后所有请求复用） ----------
_lock = threading.Lock()
_pipeline: RAGPipeline | None = None


def load_documents(root: Path) -> dict[str, str]:
    """同 scripts/01_build_index.py（教学脚本各自独立，便于单独阅读）。"""
    docs = {}
    for p in sorted(root.rglob("*")):
        if p.suffix.lower() in SUPPORTED and p.is_file():
            docs[p.stem] = p.read_text(encoding="utf-8")
    return docs


def get_pipeline() -> RAGPipeline:
    global _pipeline
    if _pipeline is not None:
        return _pipeline
    with _lock:
        if _pipeline is not None:
            return _pipeline
        index_dir = Path(os.getenv("INDEX_DIR", str(DEFAULT_INDEX_DIR)))
        pipeline = RAGPipeline()   # CHUNK_STRATEGY / VECTOR_STORE / RETRIEVAL_MODE 读 .env
        try:
            pipeline.load_index(index_dir)
        except FileNotFoundError:
            print("索引不存在，首次启动自动构建…")
            pipeline.build_index(load_documents(DATA_DIR), index_dir=index_dir)
        _pipeline = pipeline
        return pipeline


# ---------- SSE 工具 ----------
def sse(event: str, data) -> str:
    """Server-Sent Events 帧：`event: 名称\\ndata: JSON\\n\\n`。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def query_stream(question: str):
    try:
        pipeline = get_pipeline()
        for kind, payload in pipeline.query_stream(question):
            if kind == "context":
                sources = [
                    {"n": i + 1, "doc_id": c.doc_id, "text": c.text[:300]}
                    for i, c in enumerate(payload)
                ]
                yield sse("sources", sources)
            else:
                yield sse("token", {"t": payload})
        yield sse("done", {})
    except Exception as e:  # noqa: BLE001 —— 把错误也作为事件流回前端
        yield sse("error", {"message": f"{type(e).__name__}: {e}"})


# ---------- 路由 ----------
@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/config")
def config():
    p = get_pipeline()
    return {
        "chunk_strategy": p.chunk_strategy,
        "retrieval_mode": p.retrieval_mode,
        "vector_store": p.store_name,
        "top_k": p.top_k,
        "top_n": p.top_n,
        "chunks": len(p.store.chunks) if p.store is not None else 0,
    }


@app.get("/api/query")
def query(q: str):
    return StreamingResponse(
        query_stream(q),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache",
                 "X-Accel-Buffering": "no"},
    )


def main() -> None:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    print(f"Web UI: http://{host}:{port}  （Ctrl+C 退出）")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
