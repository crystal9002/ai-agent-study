"""CLI 安全 Agent：带三道防线的文件助手（ReAct + function calling）。

策略（--policy）：
    strict       只读；写/删除一律拒绝
    auto（默认） 只读自动批、写记录放行、删除 → default-deny 拒绝
    interactive  删除/危险操作走审批：tty 下逐条 y/N；非交互下生成待审记录并等待

用法：
    python scripts/02_secure_agent.py "列出沙箱文件，然后读 readme.txt 总结"
    python scripts/02_secure_agent.py "删除 attack_stage 下的所有文件" --policy auto
    python scripts/02_secure_agent.py "删除 readme.txt" --policy interactive --wait 8
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from sec.agent import SecureAgent
from sec.approval import get_store
from sec.audit import AuditLogger

DEFAULT_TASK = "列出沙箱文件，然后读 readme.txt 总结"


def on_event(ev: dict) -> None:
    t = ev.get("type")
    if t == "turn":
        print(f"\n— 第 {ev['iter']}/{ev['max']} 轮 —")
    elif t == "tool_call":
        print(f"  🔧 调用 {ev['name']}({json.dumps(ev['args'], ensure_ascii=False)[:120]})")
    elif t == "decision":
        mark = {"allow": "✅", "deny": "⛔", "flag": "🚩"}.get(ev.get("decision"), "·")
        print(f"     {mark} 决策={ev['decision']} 层级={ev.get('level')}")
        print(f"        防线: {' + '.join(ev.get('defense') or [])}")
        if ev.get("detection"):
            print(f"        注入命中: {ev['detection']}")
        if ev.get("reason"):
            print(f"        说明: {str(ev['reason'])[:140]}")
    elif t == "pending":
        print(f"  ⏳ 已生成待审批记录 id={ev['approval_id']}（等待人工批准，"
              f"可用 Web 端或重开 --policy interactive 在 tty 中批准）")
    elif t == "approval":
        print(f"  🗳 审批结果: {ev['status']}（id={ev['approval_id']}）")
    elif t == "tool_result":
        head = (ev.get("result") or "").splitlines()[0][:120] if ev.get("result") else ""
        print(f"  ↩ {head}")
    elif t == "final":
        print(f"\n📝 最终回答：\n{ev['content']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="CLI 安全 Agent")
    ap.add_argument("task", nargs="?", default=DEFAULT_TASK)
    ap.add_argument("--policy", choices=["strict", "auto", "interactive"], default="auto")
    ap.add_argument("--wait", type=float, default=None,
                    help="interactive 策略在非交互环境下的审批等待秒数")
    ap.add_argument("--max-iters", type=int, default=8)
    args = ap.parse_args()

    print(f"策略={args.policy}  沙箱=sandbox_workspace/  任务={args.task}")
    agent = SecureAgent(policy=args.policy, approval_wait=args.wait,
                        max_iters=args.max_iters, on_event=on_event)
    res = agent.run(args.task)

    blocked = [d for d in res.decisions if d.blocked]
    print("\n" + "─" * 52)
    print(f"状态: {res.status} | 工具调用: {len(res.decisions)} | 拦截: {len(blocked)} | run_id: {res.run_id}")

    # 审计与待审汇总
    audit = AuditLogger(run_id=res.run_id)
    recs = audit.tail(20)
    print(f"审计日志: {audit.path}（本次可见最近 {len(recs)} 条）")
    pendings = get_store().list(status="pending")
    if pendings:
        print(f"待审批记录 {len(pendings)} 条：")
        for a in pendings:
            print(f"  - {a.id}  {a.tool}  {json.dumps(a.args, ensure_ascii=False)[:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
