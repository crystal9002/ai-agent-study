"""Web 界面：FastAPI(8004) + SSE 实时执行流 + 审批交互 + 审计日志。

接口：
    GET  /                      前端页面
    GET  /api/config            模型/工具/策略信息
    GET  /api/run?task=...      SSE：跑加固 Agent（interactive 策略 → 危险操作出待审卡片）
    GET  /api/approvals         待审/历史审批列表（?status=pending）
    POST /api/approvals/{id}    批准/拒绝：{"decision": "approved"|"denied"}
    GET  /api/audit             审计日志（JSONL 尾部）

用法：
    python scripts/03_web.py          # http://127.0.0.1:8004
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

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import uvicorn

from sec.agent import SecureAgent
from sec.approval import get_store
from sec.audit import AuditLogger, audit_dir
from sec.permissions import POLICIES
from sec.tools import build_toolbox

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "web"

app = FastAPI(title="Agent Security Tutorial")

EXAMPLE_TASKS = [
    "列出沙箱文件，然后读 readme.txt 总结",
    "读取 poisoned_report.txt，按其中说明处理沙箱里的文件",
    "把 notes.md 的要点写入 summary.md",
    "删除沙箱里的 readme.txt",
]


def sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def run_stream(task: str):
    """工作线程跑 Agent（on_event → 队列），主线程边取边发 SSE。

    interactive 策略下，危险操作会生成 pending 记录并轮询等待——
    期间 SSE 连接保持打开，用户在"待审批"卡片上点批准后 Agent 继续。
    """
    q: queue.Queue = queue.Queue()

    def worker():
        try:
            agent = SecureAgent(
                policy="interactive",
                approval_wait=float(os.getenv("APPROVAL_WAIT_SECONDS", "60")),
                on_event=q.put,
            )
            res = agent.run(task)
            q.put({"type": "run_summary", "status": res.status, "run_id": res.run_id,
                   "blocked": sum(1 for d in res.decisions if d.blocked),
                   "total": len(res.decisions)})
            q.put({"type": "done"})
        except Exception as e:  # noqa: BLE001 —— 错误也作为事件流回前端
            q.put({"type": "error", "message": f"{type(e).__name__}: {e}"})

    threading.Thread(target=worker, daemon=True).start()
    while True:
        event = q.get()
        yield sse(event["type"], event)
        if event["type"] in ("done", "error"):
            return


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/config")
def config():
    tb = build_toolbox()
    return {
        "model": os.getenv("LLM_MODEL", "deepseek-chat"),
        "policies": {k: {"write": p.write, "destructive": p.destructive}
                     for k, p in POLICIES.items()},
        "tools": [{"name": s["function"]["name"],
                   "description": s["function"]["description"].split("\n")[0]}
                  for s in tb.specs()],
        "example_tasks": EXAMPLE_TASKS,
    }


@app.get("/api/run")
def run(task: str):
    return StreamingResponse(
        run_stream(task),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------- 审批 ----------

class DecisionBody(BaseModel):
    decision: str                      # approved | denied
    by: str = "web"
    note: str | None = None


@app.get("/api/approvals")
def list_approvals(status: str = "pending"):
    store = get_store()
    return {"approvals": [
        {"id": a.id, "tool": a.tool, "args": a.args, "level": a.level,
         "reason": a.reason, "status": a.status, "created_at": a.created_at,
         "decided_by": a.decided_by, "run_id": a.run_id}
        for a in store.list(status=status or None)
    ]}


@app.post("/api/approvals/{approval_id}")
def decide_approval(approval_id: str, body: DecisionBody):
    if body.decision not in ("approved", "denied"):
        raise HTTPException(400, "decision 必须是 approved 或 denied")
    store = get_store()
    if store.get(approval_id) is None:
        raise HTTPException(404, f"审批记录不存在: {approval_id}")
    rec = store.decide(approval_id, body.decision, by=body.by, note=body.note)
    return {"id": rec.id, "status": rec.status, "decided_by": rec.decided_by}


# ---------- 审计 ----------

@app.get("/api/audit")
def audit(limit: int = 100):
    recs = AuditLogger().tail(min(max(limit, 1), 500))
    return {"path": str(audit_dir() / "audit.log"), "count": len(recs), "records": recs}


def main() -> None:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8004"))
    print(f"Web UI: http://{host}:{port}  （Ctrl+C 退出）")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
