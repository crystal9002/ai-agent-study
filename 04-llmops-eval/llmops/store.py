"""runs/ 目录管理：落盘、登记 index.jsonl、读取（供 04_report 与 05_web）。

目录约定：
    runs/
    ├── index.jsonl        # 每次运行追加一行登记（run_id/name/kind/ts/summary）
    ├── <run_id>.jsonl     # 单次运行完整记录（首行 meta + summary，其后每行一个 span/case）
"""
from __future__ import annotations

import json
import time
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"
INDEX_PATH = RUNS_DIR / "index.jsonl"


def _ensure() -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


def save_run(kind: str, name: str, record: dict) -> str:
    """保存一次运行并登记到 index.jsonl，返回 run_id。

    kind: trace | eval_rag | eval_agent（仪表盘按此分类）
    record: Trace.finish() 的 dict，或评估运行的 dict（含 cases + report）
    """
    _ensure()
    run_id = record.get("run_id") or time.strftime("%Y%m%d-%H%M%S-") + name
    record = dict(record)
    record["run_id"] = run_id
    record["kind"] = kind
    record["name"] = name
    record.setdefault("started_at", time.strftime("%Y-%m-%d %H:%M:%S"))

    path = RUNS_DIR / f"{run_id}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        # 首行：meta（不含 spans/cases 明细）
        head = {k: v for k, v in record.items() if k not in ("spans", "cases")}
        f.write(json.dumps({"_type": "meta", **head}, ensure_ascii=False) + "\n")
        for span in record.get("spans", []):
            f.write(json.dumps({"_type": "span", **span}, ensure_ascii=False) + "\n")
        for case in record.get("cases", []):
            f.write(json.dumps({"_type": "case", **case}, ensure_ascii=False) + "\n")

    entry = {
        "run_id": run_id,
        "kind": kind,
        "name": name,
        "ts": record["started_at"],
        "summary": record.get("summary", {}),
        "report": record.get("report", {}),
        "meta": record.get("meta", {}),
    }
    with INDEX_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return run_id


def list_runs(kind: str | None = None) -> list[dict]:
    """读 index.jsonl，返回运行列表（新的在前）。可按 kind 过滤。"""
    if not INDEX_PATH.exists():
        return []
    entries: list[dict] = []
    with INDEX_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if kind is None or e.get("kind") == kind:
                entries.append(e)
    entries.sort(key=lambda e: e.get("ts", ""), reverse=True)
    return entries


def load_run(run_id: str) -> dict | None:
    """读取单次运行的完整记录（meta + spans + cases）。"""
    path = RUNS_DIR / f"{run_id}.jsonl"
    if not path.exists():
        return None
    meta: dict = {}
    spans: list[dict] = []
    cases: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = row.pop("_type", None)
            if t == "meta":
                meta = row
            elif t == "span":
                spans.append(row)
            elif t == "case":
                cases.append(row)
    meta["spans"] = spans
    meta["cases"] = cases
    return meta


def latest_two_evals(kind: str = "eval_rag") -> list[dict]:
    """取最近两次同类评估（供 04_report 默认对比）。"""
    return list_runs(kind)[:2][::-1]
