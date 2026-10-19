"""04 · 汇总与回归对比：趋势 + 两次运行 diff（指标下降超阈值标红）。

回归检测思路（对应 docs/05-regression.md）：
    新旧两次同类评估（eval_rag / eval_agent）逐指标相减，
    下降超过 REGRESSION_THRESHOLD（默认 0.05）→ 🔴 回归；上升 → 🟢；否则 ≈。

用法：
    .venv/bin/python scripts/04_report.py                    # 自动取最近两次同类评估对比
    .venv/bin/python scripts/04_report.py --kind eval_agent
    .venv/bin/python scripts/04_report.py --old <run_id> --new <run_id>
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from llmops.store import list_runs, load_run

THRESHOLD = float(os.getenv("REGRESSION_THRESHOLD", "0.05"))


def print_trend(kind: str) -> None:
    runs = list_runs(kind)
    if not runs:
        print(f"（index.jsonl 中没有 {kind} 记录，先跑 02/03 生成评估）")
        return
    print(f"═══ {kind} 趋势（{len(runs)} 次，旧 → 新）═══")
    # 反转成时间正序
    for e in reversed(runs):
        r = e.get("report") or {}
        rate = r.get("pass_rate")
        extra = ""
        m = r.get("metrics") or {}
        j = r.get("judge") or {}
        if "hit@3" in m:
            extra = f"  hit@3={m.get('hit@3')}  containment={m.get('containment')}"
            if j.get("faithfulness") is not None:
                extra += f"  faithfulness={j['faithfulness']}"
        elif "tools_ok" in m:
            extra = f"  tools_ok={m.get('tools_ok')}  turns={m.get('turns')}"
        rate_s = f"{rate:.1%}" if isinstance(rate, (int, float)) else "—"
        print(f"  {e['ts']}  {e['run_id']}  pass_rate={rate_s}{extra}")


def _flatten(report: dict) -> dict:
    """把 report 摊平成 {指标名: 数值} 便于 diff。"""
    out: dict = {}
    if report.get("pass_rate") is not None:
        out["pass_rate"] = report["pass_rate"]
    for k, v in (report.get("metrics") or {}).items():
        if v is not None:
            out[k] = v
    for k, v in (report.get("judge") or {}).items():
        if v is not None:
            out[f"judge_{k}"] = v
    return out


def diff(old_id: str, new_id: str) -> None:
    old, new = load_run(old_id), load_run(new_id)
    if not old or not new:
        print(f"找不到运行记录: {old_id if not old else new_id}")
        return
    print(f"\n═══ 回归对比 ═══")
    print(f"旧: {old_id}  ({old.get('started_at')})")
    print(f"新: {new_id}  ({new.get('started_at')})")
    print(f"阈值: 下降 > {THRESHOLD} 标红 🔴\n")

    fo, fn = _flatten(old.get("report") or {}), _flatten(new.get("report") or {})
    keys = sorted(set(fo) | set(fn))
    regressions = 0
    improvements = 0
    print(f"  {'指标':<22} {'旧':>10} {'新':>10} {'Δ':>10}  判定")
    for k in keys:
        o, n = fo.get(k), fn.get(k)
        if o is None or n is None:
            print(f"  {k:<22} {str(o):>10} {str(n):>10} {'—':>10}  （单侧缺失，跳过）")
            continue
        d = n - o
        if d < -THRESHOLD:
            flag, regressions = "🔴 回归", regressions + 1
        elif d > THRESHOLD:
            flag, improvements = "🟢 提升", improvements + 1
        else:
            flag = "≈ 持平"
        print(f"  {k:<22} {o:>10.4f} {n:>10.4f} {d:>+10.4f}  {flag}")

    print(f"\n汇总: 🔴 回归 {regressions} 项 · 🟢 提升 {improvements} 项 · 其余持平")
    if regressions:
        print("结论: 存在回归，建议对照 runs/<id>.cases.json 逐条看 badcase，")
        print("      确认是 prompt 退化还是 judge 波动（judge 单维下降 0.5 内属正常噪声）。")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="eval_rag", choices=["eval_rag", "eval_agent", "trace"])
    ap.add_argument("--old", default="", help="旧 run_id")
    ap.add_argument("--new", default="", help="新 run_id")
    args = ap.parse_args()

    print_trend(args.kind)

    if args.old and args.new:
        old_id, new_id = args.old, args.new
    else:
        runs = [e for e in list_runs(args.kind) if e.get("report", {}).get("pass_rate") is not None]
        if len(runs) < 2:
            print(f"\n（{args.kind} 有效评估不足两次，无法对比；再跑一次 02/03 即可）")
            return
        new_id, old_id = runs[0]["run_id"], runs[1]["run_id"]

    diff(old_id, new_id)


if __name__ == "__main__":
    main()
