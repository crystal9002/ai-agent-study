"""审计日志：三道防线的"黑匣子"。

每条工具调用（无论放行/拒绝/待审）都落一行 JSONL：
    ts / who / run_id / tool / args / decision / level /
    detection（注入命中）/ result_preview / duration_ms

文件位置：<tutorial>/audit/audit.log（可用 .env 的 AUDIT_DIR 改）。
Web 端 GET /api/audit 直接读它——审计与展示解耦：Agent 只管追加。
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def audit_dir() -> Path:
    d = os.getenv("AUDIT_DIR", "audit")
    p = Path(d)
    return p if p.is_absolute() else ROOT / p


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


class AuditLogger:
    """追加式 JSONL 审计。线程安全（Web 端多 worker 线程共用一个实例）。"""

    def __init__(self, run_id: str | None = None, who: str = "agent"):
        self.dir = audit_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "audit.log"
        self.run_id = run_id or new_run_id()
        self.who = who
        self._lock = threading.Lock()

    def log(
        self,
        tool: str,
        args: dict | str | None,
        decision: str,
        level: str | None = None,
        result: str | None = None,
        detection: list | None = None,
        defense: list | None = None,
        duration_ms: int | None = None,
        note: str | None = None,
    ) -> dict:
        """写一条审计记录并返回它（result 截断预览，防日志撑爆/泄密）。"""
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"raw": args}
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "who": self.who,
            "run_id": self.run_id,
            "tool": tool,
            "args": args,
            "decision": decision,          # allow | deny | need_approval | blocked
            "level": level,
            "defense": defense or [],      # 哪道/哪些防线参与了决策
            "detection": detection or [],  # 注入扫描命中
            "result_preview": (result or "")[:500],
            "duration_ms": duration_ms,
            "note": note,
        }
        line = json.dumps(rec, ensure_ascii=False)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        return rec

    def tail(self, n: int = 100) -> list[dict]:
        """读最近 n 条审计记录（Web / CLI 汇报用）。"""
        return read_tail(self.path, n)


def read_tail(path: Path, n: int = 100) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
