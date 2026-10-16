"""原生版：任务规划型 Agent（规划 → 逐步 ReAct 执行 → 汇总）。

用法：
    python scripts/01_task_agent.py "下周二到周四去上海出差，帮我安排行程"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import TaskAgent

DEFAULT_GOAL = "下周二到周四去上海出差（从北京出发），帮我安排完整的差旅行程"


def main() -> None:
    goal = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GOAL
    print(f"🎯 目标: {goal}\n" + "=" * 60)

    agent = TaskAgent()
    try:
        answer = agent.run(goal)
    except Exception as e:  # API/规划失败给出明确提示
        print(f"❌ 运行失败: {type(e).__name__}: {e}")
        print("请检查 .env 中的 OPENAI_BASE_URL / OPENAI_API_KEY / LLM_MODEL")
        return

    print("\n" + "=" * 60)
    print("📄 最终方案:\n")
    print(answer)

    # 让 Agent 自己把方案存成文件（用到 save_itinerary 工具）：
    # 这里作为演示，在汇总后再走一次单轮工具调用
    out = Path(__file__).parent.parent / "output" / "itinerary.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(answer, encoding="utf-8")
    print(f"\n💾 已保存: {out}")


if __name__ == "__main__":
    main()
