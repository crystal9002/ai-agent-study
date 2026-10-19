"""③ 多智能体 CLI：supervisor 路由 → 3 个 worker 分工 → 事件轨迹全打印。

默认目标拆成三步（恰好各落到一个 worker）：
  查团队版定价（researcher）→ 算 50 人年费（calculator）→ 写 summary.md（writer）

用法：
  python scripts/03_multi_agent.py
  python scripts/03_multi_agent.py "企业版 80 人首年含税总预算，写成 budget.md"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from multi.runner import run

DEFAULT_GOAL = "查团队版定价，算 50 人一年的总费用（如有年付折扣请计入），写成 summary.md"


def main() -> None:
    goal = sys.argv[1].strip() if len(sys.argv) > 1 else DEFAULT_GOAL
    print(f"🎯 目标: {goal}\n")
    print("=" * 60)
    final = run(goal)
    print("=" * 60)
    out = Path(__file__).resolve().parent.parent / "output" / "summary.md"
    if out.exists():
        print(f"\n📄 产物: {out}")
        print("-" * 40)
        print(out.read_text(encoding="utf-8")[:600])
    print(f"\n🏁 收尾结论:\n{final}")


if __name__ == "__main__":
    main()
