"""防线②：工具权限（三级）+ 路径沙箱 + shell 双防线。

设计对照 AI-Agent开发教程/012-进阶练习清单.md 练习 1（run_shell 白名单），
本课把它系统化成可配置的策略层：

    三级权限   read（自动放行）/ write（记录放行）/ destructive（需审批，默认拒绝）
    路径沙箱   realpath 后必须落在 sandbox_workspace 内，天然防 ../ 穿越
    命令双防线  黑名单拦危险变体 + 白名单定主力 + shell=False + 超时兜底
    default-deny  不在策略里的工具/级别一律拒绝
"""
from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


# ---------- 三级权限 ----------

class Level(str, Enum):
    READ = "read"                # 只读：自动放行
    WRITE = "write"              # 写入：可逆，记录审计后放行
    DESTRUCTIVE = "destructive"  # 破坏性/不可逆：必须人工审批


TOOL_LEVELS: dict[str, Level] = {
    "list_files": Level.READ,
    "read_file": Level.READ,
    "run_shell": Level.READ,       # 只有通过白名单的只读命令才会真执行
    "write_file": Level.WRITE,
    "delete_file": Level.DESTRUCTIVE,
}


def level_for(tool: str) -> Level | None:
    """未知工具 → None（default-deny：不是注册表里的工具一律不放行）。"""
    return TOOL_LEVELS.get(tool)


# ---------- 可配置策略 ----------

@dataclass(frozen=True)
class Policy:
    name: str
    write: str        # "allow" | "deny"
    destructive: str  # "ask"（生成审批记录）| "deny"（直接拒绝）

    def decide(self, tool: str, level: Level | None) -> tuple[str, str]:
        """返回 (allow|deny|need_approval, 理由)。"""
        if level is None:
            return "deny", f"未知工具 {tool}，不在权限注册表中（default-deny）"
        if level is Level.READ:
            return "allow", "只读操作，自动放行"
        if level is Level.WRITE:
            if self.write == "allow":
                return "allow", "写操作可逆，记录审计后放行"
            return "deny", f"策略 {self.name} 禁止写操作"
        # destructive
        if self.destructive == "deny":
            return "deny", f"策略 {self.name} 直接拒绝破坏性操作（default-deny）"
        return "need_approval", "破坏性操作不可逆，必须人工批准"


POLICIES: dict[str, Policy] = {
    # strict   ：最小权限，只读；写/破坏性硬拒绝（连审批入口都不给）
    # auto      ：只读自动批、写记录放行、破坏性走审批闸门
    #            （闸门默认 APPROVAL_MODE=deny → 等效"拒绝"，即 spec 的
    #             "destructive 拒绝或走 --interactive 批准"）
    # interactive：与 auto 相同，但审批闸门强制 ask（tty 逐条问 / Web 出待审卡片）
    "strict": Policy("strict", write="deny", destructive="deny"),
    "auto": Policy("auto", write="allow", destructive="ask"),
    "interactive": Policy("interactive", write="allow", destructive="ask"),
}


def load_policy(name: str | None = None) -> Policy:
    name = name or os.getenv("POLICY", "auto")
    if name not in POLICIES:
        raise ValueError(f"未知策略: {name}，可选 {sorted(POLICIES)}")
    return POLICIES[name]


# ---------- 路径沙箱 ----------

class PathSandbox:
    """路径沙箱：解析后必须位于 root 内，否则拒绝。

    防御的攻击：
      - ../ 逐级穿越（foo/../../etc/passwd）
      - 绝对路径直指沙箱外（/etc/passwd）
      - 软链接逃逸（resolve() 会把软链接的真实目标也解析出来再校验）
    """

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    def resolve(self, path: str) -> tuple[Path | None, str | None]:
        """成功返回 (绝对路径, None)，失败返回 (None, 拒绝原因)。"""
        if not path or not str(path).strip():
            return None, "路径为空"
        if "\x00" in str(path):
            return None, "路径含非法字符"
        p = Path(str(path)).expanduser()
        cand = p if p.is_absolute() else (self.root / p)
        try:
            resolved = cand.resolve()
        except OSError as e:
            return None, f"路径解析失败: {e}"
        if resolved != self.root and self.root not in resolved.parents:
            return None, f"路径越界（沙箱={self.root}）: {path} → {resolved}"
        return resolved, None


# ---------- shell 双防线（对照 012 练习 1）----------

# 白名单（主力）：只放行明确安全的只读命令
ALLOWED_SHELL: set[str] = {"ls", "pwd", "cat", "grep", "wc", "head", "tail", "du", "df", "echo"}

# 黑名单（拦变体）：白名单命令的危险参数、逃逸手法、出网命令
DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    ("rm_variant", r"(\b|/)(rm|rmdir|unlink)\b"),
    ("privilege", r"\b(sudo|su|chroot|pkexec)\b"),
    ("format", r"\b(mkfs|diskutil|fdisk|dd)\b"),
    ("redirect_root", r">\s*/"),
    ("pipe_shell", r"\|\s*(ba)?sh\b|\|\s*python"),
    ("perm_open", r"chmod\s+(-R\s+)?777|chmod\s+\+s"),
    ("cron_persist", r"\bcrontab\b|/etc/cron"),
    ("egress", r"\b(curl|wget|nc|ncat|netcat|ssh|scp|ftp|telnet)\b"),
    ("substitution", r"\$\(|`"),
    ("chained", r"[;&|]|&&|\|\|"),
    ("sensitive_path", r"/etc/shadow|id_rsa|\.aws/|\.ssh/|\.env\b|/proc/self"),
]
_COMPILED_DANGER = [(n, re.compile(p)) for n, p in DANGEROUS_PATTERNS]


@dataclass
class ShellVerdict:
    ok: bool
    reason: str = ""
    argv: list[str] | None = None


def check_shell(command: str) -> ShellVerdict:
    """命令三连检：黑名单 → 白名单 → 参数级敏感路径。"""
    cmd = (command or "").strip()
    if not cmd:
        return ShellVerdict(False, "命令为空")

    # 1) 第一道防线：黑名单（拦截变体与链式注入）
    for name, rx in _COMPILED_DANGER:
        if rx.search(cmd):
            return ShellVerdict(False, f"黑名单命中[{name}]: {rx.pattern}")

    # 2) 第二道防线：白名单（首命令必须是只读命令）
    try:
        argv = shlex.split(cmd)
    except ValueError as e:
        return ShellVerdict(False, f"命令解析失败: {e}")
    if not argv:
        return ShellVerdict(False, "命令为空")
    first = Path(argv[0]).name
    if first not in ALLOWED_SHELL:
        return ShellVerdict(False, f"{first} 不在白名单，允许: {sorted(ALLOWED_SHELL)}")

    # 3) 参数级校验（黑名单已含敏感路径，这里再兜一层绝对路径）
    for a in argv[1:]:
        if a.startswith("/") and not a.startswith(("/tmp", "/dev/null")):
            return ShellVerdict(False, f"禁止访问沙箱外绝对路径: {a}")

    return ShellVerdict(True, "白名单通过", argv=argv)


def check_path(path: str, sandbox: PathSandbox) -> tuple[Path | None, str | None]:
    """路径白名单 + 沙箱校验的统一入口。"""
    return sandbox.resolve(path)
