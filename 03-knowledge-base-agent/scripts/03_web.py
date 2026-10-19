"""第三步：Web 界面（FastAPI + SSE 实时进度推送，端口 8002）。

命令行版（02_kb_agent.py）只能看终端打印；网页版把 Agent 的每一步推到浏览器：
    start       → 显示问题与可用工具（相当于"开场"事件）
    tool_call   → 实时显示调用了什么工具、什么参数
    tool_result → 工具返回数据（检索结果带 [n] 引用编号）
    final       → 最终带引用的回答（Markdown 渲染）

实现要点（与 01 RAG Web 的区别）：
KBAgent.run() 是同步阻塞的——on_event 回调在工作线程里触发、塞进线程安全的
queue.Queue，SSE 生成器边取边发。这是"把同步长任务接到 SSE"的标准姿势。

用法：
    .venv/bin/python scripts/03_web.py                 # http://127.0.0.1:8002
    PORT=9000 .venv/bin/python scripts/03_web.py
    curl -s -G http://127.0.0.1:8002/api/query --data-urlencode "q=团队版多少钱"
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

from kba import KBAgent, register_default_tools

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "web"

app = FastAPI(title="Knowledge Base Agent Tutorial")


def sse(event: str, data) -> str:
    """Server-Sent Events 帧：`event: 名称\\ndata: JSON\\n\\n`。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def run_stream(question: str):
    """工作线程跑 Agent（on_event → 队列），主线程边取事件边发 SSE。"""
    q: queue.Queue = queue.Queue()

    def worker():
        try:
            KBAgent().run(question, on_event=q.put)
            q.put({"type": "done"})
        except Exception as e:  # noqa: BLE001 —— 错误也作为事件流回前端
            q.put({"type": "error", "message": f"{type(e).__name__}: {e}"})

    threading.Thread(target=worker, daemon=True).start()
    while True:
        event = q.get()          # 阻塞等待下一个事件 → 实时推送
        yield sse(event["type"], event)
        if event["type"] in ("done", "error"):
            return


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/config")
def config():
    specs = register_default_tools().specs()
    return {
        "tools": [{"name": s["function"]["name"],
                   "description": s["function"]["description"]} for s in specs],
        "model": os.getenv("LLM_MODEL", "deepseek-chat"),
    }


@app.get("/api/query")
def query(q: str):
    """SSE 端点。中文参数必须 URL 编码（curl 用 --data-urlencode）。"""
    return StreamingResponse(
        run_stream(q),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def main() -> None:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8002"))
    print(f"Web UI: http://{host}:{port}  （Ctrl+C 退出）")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
