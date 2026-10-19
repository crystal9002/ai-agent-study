"""02 · RAG 离线评估：全量跑 data/golden_rag.jsonl 并打分。

指标：
- 检索层：hit@3 / precision@3 / mrr（硬指标，不花钱）
- 生成层：containment（关键串包含）+ LLM judge 忠实度/相关性（1~5，judge 失败降级 null）

用法：
    .venv/bin/python scripts/02_eval_rag.py                 # 全量 12 条，含 judge
    .venv/bin/python scripts/02_eval_rag.py --no-judge      # 只跑硬指标（省钱/离线调试）
    .venv/bin/python scripts/02_eval_rag.py --limit 3       # 先跑 3 条冒烟
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from llmops.runner import load_jsonl, run_rag_eval
from llmops.store import save_run

DATA = Path(__file__).resolve().parent.parent / "data" / "golden_rag.jsonl"


def print_report(report: dict) -> None:
    print("\n═══════ RAG 评估报告 ═══════")
    print(f"用例总数: {report['total']}   通过: {report['passed']}   "
          f"通过率: {report['pass_rate']:.1%}   错误: {report['errors']}")
    print(f"平均延迟: {report['avg_latency_ms']:.0f}ms")
    print("── 硬指标 ──")
    for k, v in (report.get("metrics") or {}).items():
        print(f"  {k:<14} {v if v is not None else '—'}")
    print("── LLM Judge（1~5）──")
    j = report.get("judge") or {}
    if not j:
        print("  （未启用或全部降级）")
    for k, v in j.items():
        print(f"  {k:<14} {v if v is not None else '—'}")
    cov = report.get("judge_coverage")
    if cov is not None:
        print(f"  judge 成功率: {cov:.0%}（降级的不计入均分）")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-judge", action="store_true", help="跳过 LLM-as-judge")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条")
    ap.add_argument("--k", type=int, default=3, help="hit@k / precision@k 的 k")
    args = ap.parse_args()

    cases = load_jsonl(DATA)
    if args.limit:
        cases = cases[: args.limit]
    print(f"加载 golden set: {len(cases)} 条（judge={'关' if args.no_judge else '开'}）\n")

    record = run_rag_eval(cases, use_judge=not args.no_judge, k=args.k)
    print_report(record["report"])

    run_id = save_run("eval_rag", "eval_rag", record)
    # 单条明细也存一份独立 JSON，方便 badcase 回流人工看
    detail = Path(__file__).resolve().parent.parent / "runs" / f"{run_id}.cases.json"
    detail.write_text(json.dumps(record["cases"], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已保存 → runs/{run_id}.jsonl  明细 → runs/{run_id}.cases.json")


if __name__ == "__main__":
    main()
