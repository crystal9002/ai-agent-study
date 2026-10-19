"""防线③：危险操作人工审批（human-in-the-loop）。

核心原则（docs/04-human-in-the-loop.md）：
    default-deny —— 破坏性操作（不可逆 / 出网 / 越权）在拿到人工批准前，
    一律不执行；非交互环境超时/无人值守 = 拒绝。

两种批准方式（共用同一个 ApprovalStore）：
    命令行   Gate.ask() 在 tty 下逐条 y/N；非交互下生成 pending 并轮询等待
    HTTP     Web 端 GET /api/approvals 拿待审列表，POST /api/approvals/{id} 批准/拒绝

状态机：pending → approved / denied / expired（超时）。
记录持久化到 audit/approvals.jsonl（追加事件，重放可恢复状态）。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sec.audit import audit_dir

STATUSES = ("pending", "approved", "denied", "expired")


@dataclass
class Approval:
    id: str
    tool: str
    args: dict
    level: str
    reason: str
    run_id: str
    status: str = "pending"
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    decided_by: str | None = None   # human / web / policy / timeout
    decided_at: str | None = None
    decision_note: str | None = None


class ApprovalStore:
    """审批记录存储：内存态 + JSONL 事件日志，进程内单例共享。"""

    def __init__(self, path: Path | None = None):
        self.path = path or (audit_dir() / "approvals.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._items: dict[str, Approval] = {}
        self._load()

    def _load(self) -> None:
        """重放事件日志，恢复最新状态。"""
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = ev.get("event")
            if kind == "created":
                rec = Approval(**{k: v for k, v in ev.items() if k != "event"})
                self._items[rec.id] = rec
            elif kind == "decided" and ev.get("id") in self._items:
                rec = self._items[ev["id"]]
                rec.status = ev.get("status", rec.status)
                rec.decided_by = ev.get("decided_by")
                rec.decided_at = ev.get("decided_at")
                rec.decision_note = ev.get("decision_note")

    def _append(self, event: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def create(self, tool: str, args: dict, level: str, reason: str, run_id: str) -> Approval:
        aid = f"apr-{int(time.time() * 1000) % 10_000_000:07d}"
        rec = Approval(id=aid, tool=tool, args=args, level=level, reason=reason, run_id=run_id)
        with self._lock:
            self._items[aid] = rec
            self._append({"event": "created", **asdict(rec)})
        return rec

    def get(self, approval_id: str) -> Approval | None:
        return self._items.get(approval_id)

    def list(self, status: str | None = None) -> list[Approval]:
        items = list(self._items.values())
        if status:
            items = [a for a in items if a.status == status]
        return sorted(items, key=lambda a: a.created_at, reverse=True)

    def decide(self, approval_id: str, decision: str, by: str = "human",
               note: str | None = None) -> Approval | None:
        """批准/拒绝一个 pending 记录。decision ∈ {approved, denied}。"""
        if decision not in ("approved", "denied"):
            raise ValueError(f"decision 必须是 approved/denied，收到 {decision}")
        with self._lock:
            rec = self._items.get(approval_id)
            if rec is None:
                return None
            if rec.status != "pending":
                return rec  # 已有结论，幂等返回
            rec.status = decision
            rec.decided_by = by
            rec.decided_at = time.strftime("%Y-%m-%dT%H:%M:%S")
            rec.decision_note = note
            self._append({
                "event": "decided", "id": approval_id, "status": decision,
                "decided_by": by, "decided_at": rec.decided_at, "decision_note": note,
            })
            return rec

    def _expire(self, approval_id: str) -> None:
        with self._lock:
            rec = self._items.get(approval_id)
            if rec and rec.status == "pending":
                rec.status = "expired"
                rec.decided_by = "timeout"
                rec.decided_at = time.strftime("%Y-%m-%dT%H:%M:%S")
                self._append({
                    "event": "decided", "id": approval_id, "status": "expired",
                    "decided_by": "timeout", "decided_at": rec.decided_at,
                })


_store: ApprovalStore | None = None
_store_lock = threading.Lock()


def get_store() -> ApprovalStore:
    """进程内单例：Agent 与 Web 端共享同一份待审列表。"""
    global _store
    with _store_lock:
        if _store is None:
            _store = ApprovalStore()
        return _store


class ApprovalGate:
    """审批闸门：把 need_approval 的工具调用变成"等人点头"。

    mode:
        deny —— 非交互默认：不等人，直接拒绝（default-deny）
        ask  —— tty 下命令行逐条问；非交互下生成 pending 并轮询等待
    """

    def __init__(self, mode: str | None = None, wait_seconds: float | None = None,
                 store: ApprovalStore | None = None, on_event=None):
        self.mode = mode or os.getenv("APPROVAL_MODE", "deny")
        self.wait_seconds = (
            wait_seconds if wait_seconds is not None
            else float(os.getenv("APPROVAL_WAIT_SECONDS", "60"))
        )
        self.store = store or get_store()
        self.on_event = on_event or (lambda ev: None)

    def ask(self, tool: str, args: dict, level: str, reason: str,
            run_id: str) -> tuple[str, str, str | None]:
        """请求批准。返回 (allow|deny, 给 LLM 回填的消息, approval_id|None)。"""
        if self.mode != "ask":
            msg = (f"DENIED: 危险操作未获人工批准（default-deny，APPROVAL_MODE=deny）。"
                   f"工具={tool} 参数={args} 原因={reason}")
            return "deny", msg, None

        rec = self.store.create(tool, args, level, reason, run_id)
        self.on_event({
            "type": "pending", "approval_id": rec.id, "tool": tool,
            "args": args, "reason": reason,
        })

        # tty 环境：命令行逐条问
        if sys.stdin is not None and sys.stdin.isatty():
            answer = self._cli_prompt(rec)
            if answer == "y":
                self.store.decide(rec.id, "approved", by="human")
                self.on_event({"type": "approval", "approval_id": rec.id, "status": "approved"})
                return "allow", f"用户已在命令行批准该操作（approval_id={rec.id}）", rec.id
            self.store.decide(rec.id, "denied", by="human")
            self.on_event({"type": "approval", "approval_id": rec.id, "status": "denied"})
            return "deny", f"用户拒绝了该操作（approval_id={rec.id}）。请告知用户并调整方案。", rec.id

        # 非交互：轮询等待 Web 端批准；超时 = 拒绝
        deadline = time.time() + self.wait_seconds
        while time.time() < deadline:
            cur = self.store.get(rec.id)
            if cur and cur.status == "approved":
                self.on_event({"type": "approval", "approval_id": rec.id, "status": "approved"})
                return "allow", f"人工已批准（approval_id={rec.id}）", rec.id
            if cur and cur.status == "denied":
                self.on_event({"type": "approval", "approval_id": rec.id, "status": "denied"})
                return "deny", f"人工拒绝了该操作（approval_id={rec.id}）。请调整方案。", rec.id
            time.sleep(1.0)
        self.store._expire(rec.id)
        self.on_event({"type": "approval", "approval_id": rec.id, "status": "expired"})
        return ("deny",
                f"DENIED: 等待人工审批超时（{self.wait_seconds:.0f}s），按 default-deny 拒绝。"
                f"approval_id={rec.id}", rec.id)

    @staticmethod
    def _cli_prompt(rec: Approval) -> str:
        print("\n" + "=" * 52)
        print(f"⚠ 待审批操作  id={rec.id}")
        print(f"  工具: {rec.tool}   级别: {rec.level}")
        print(f"  参数: {json.dumps(rec.args, ensure_ascii=False)}")
        print(f"  原因: {rec.reason}")
        print("=" * 52)
        try:
            return input("批准执行? [y/N] ").strip().lower()
        except EOFError:
            return "n"
