"""05 · Web 仪表盘（FastAPI，端口 8003）：运行列表 / span 树 / 评估历史。

接口：
    GET /                 前端单页 web/index.html
    GET /api/runs         运行列表（index.jsonl，可 ?kind= 过滤）
    GET /api/runs/{id}    单次运行详情（meta + report + spans 树 + cases）
    GET /api/evals        评估历史（kind 为 eval_* 的运行，供前端画趋势）

前端轮询拉取（评估是离线批量跑的，不需要 SSE；对比 02 教程的 SSE 场景）。

用法：
    .venv/bin/python scripts/05_web.py            # http://127.0.0.1:8003
    PORT=9000 .venv/bin/python scripts/05_web.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
import uvicorn

from llmops.store import list_runs, load_run

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="LLMOps Eval Dashboard")


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/api/runs")
def api_runs(kind: str | None = None):
    return {"runs": list_runs(kind)}


@app.get("/api/runs/{run_id}")
def api_run(run_id: str):
    rec = load_run(run_id)
    if rec is None:
        raise HTTPException(404, f"run {run_id} 不存在")
    return rec


@app.get("/api/evals")
def api_evals():
    """评估历史：eval_rag + eval_agent 合并，按时间正序，供趋势图使用。"""
    evals = list_runs("eval_rag") + list_runs("eval_agent")
    evals.sort(key=lambda e: e.get("ts", ""))
    return {"evals": evals}


def main() -> None:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8003"))
    print(f"LLMOps 仪表盘: http://{host}:{port}  （Ctrl+C 退出）")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
