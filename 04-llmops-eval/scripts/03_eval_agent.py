"""03 · Agent 评估：全量跑 data/golden_agent.jsonl，看任务成功率。

被测对象是 llmops/sut_agent.py 里那个极简 Function Calling Agent。
每条用例断言三件事：
    tools_ok     必调工具都调了吗（must_call_tools ⊆ 实际调用）
    answer_ok    答案过断言了吗（success_regex 或 expected_contains）
    turns_ok     没超轮次、没报错

用法：
    .venv/bin/python scripts/03_eval_agent.py
    .venv/bin/python scripts/03_eval_agent.py --limit 2
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from llmops.runner import load_jsonl, run_agent_eval
from llmops.store import save_run

DATA = Path(__file__).resolve().parent.parent / "data" / "golden_agent.jsonl"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    cases = load_jsonl(DATA)
    if args.limit:
        cases = cases[: args.limit]
    print(f"加载 Agent golden set: {len(cases)} 条\n")

    record = run_agent_eval(cases)
    report = record["report"]

    print("\n═══════ Agent 评估报告 ═══════")
    print(f"用例总数: {report['total']}   成功: {report['passed']}   "
          f"成功率: {report['pass_rate']:.1%}   错误: {report['errors']}")
    print(f"平均延迟: {report['avg_latency_ms']:.0f}ms")
    for k, v in (report.get("metrics") or {}).items():
        label = {"tools_ok": "工具选择正确率", "answer_ok": "答案断言通过率", "turns": "平均轮次"}.get(k, k)
        print(f"  {label:<12} {v if v is not None else '—'}")

    # 列出失败用例，方便 badcase 分析
    failed = [c for c in record["cases"] if not c["passed"]]
    if failed:
        print("\n── 失败用例 ──")
        for c in failed:
            why = c["error"] or f"metrics={c['metrics']}"
            print(f"  ✗ {c['id']}  {why}")
            if c["answer"]:
                print(f"    答案: {c['answer'][:120]}")

    run_id = save_run("eval_agent", "eval_agent", record)
    print(f"\n已保存 → runs/{run_id}.jsonl")


if __name__ == "__main__":
    main()
