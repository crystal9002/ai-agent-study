"""sec —— Agent 安全实战：三道防线的原生实现。

模块分工：
    injection.py   防线① 注入检测与内容隔离（UNTRUSTED 包装）
    permissions.py 防线② 三级权限 + 路径沙箱 + 命令白名单/黑名单
    approval.py    防线③ 危险操作人工审批（human-in-the-loop）
    audit.py       贯穿三道防线的审计日志（JSONL）
    tools.py       安全工具集（物理沙箱的最后一道保险丝）
    agent.py       安全 Agent 循环（ReAct + 三道防线编排）
    attacks.py     3 个攻击演示场景（红队用例）
"""

__all__ = [
    "injection",
    "permissions",
    "approval",
    "audit",
    "tools",
    "agent",
    "attacks",
]
