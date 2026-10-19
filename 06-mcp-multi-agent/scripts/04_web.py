"""④ Web 界面：FastAPI + SSE，实时展示 supervisor 路由 → worker 分发 → 汇总。

实现模式（与 02 教程 03_web.py 同款）：
  multi.runner.run() 是同步阻塞的 → 工作线程里跑、on_event 塞进线程安全的
  queue.Queue → SSE 生成器边取边发。"同步长任务接 SSE"的标准姿势。

用法：
  python scripts/04_web.py            # http://127.0.0.1:8005
  curl -N -G 'http://127.0.0.1:8005/api/run' --data-urlencode 'goal=查团队版定价'
"""
import json
import os
import queue
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
import uvicorn

from multi.runner import run as run_multi

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "web"

app = FastAPI(title="MCP + Multi-Agent Tutorial")

WORKERS = [
    {"name": "researcher", "role": "检索", "tools": ["search_kb"]},
    {"name": "calculator", "role": "计算", "tools": ["calc"]},
    {"name": "writer", "role": "写作", "tools": ["save"]},
]


def sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def run_stream(goal: str):
    """工作线程跑多智能体（on_event → 队列），主线程边取边发 SSE。"""
    q: queue.Queue = queue.Queue()

    def worker():
        try:
            run_multi(goal, on_event=q.put, verbose=False)
            q.put({"type": "done"})
        except Exception as e:  # noqa: BLE001 —— 错误也走事件流回前端
            q.put({"type": "error", "message": f"{type(e).__name__}: {e}"})

    threading.Thread(target=worker, daemon=True).start()
    while True:
        event = q.get()
        if event["type"] in ("done", "error"):
            yield sse(event["type"], event)
            return
        yield sse(event["type"], event)


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/config")
def config():
    return {
        "model": os.getenv("LLM_MODEL", "deepseek-chat"),
        "workers": WORKERS,
        "supervisor": {"name": "supervisor", "role": "调度"},
    }


@app.get("/api/run")
def run(goal: str):
    return StreamingResponse(
        run_stream(goal),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def main() -> None:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8005"))
    print(f"Web UI: http://{host}:{port}  （Ctrl+C 退出）")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
