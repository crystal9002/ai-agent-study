"""安全工具集：文件助手 Agent 的 5 个工具 + 物理层最后保险丝。

与 02-agent-tutorial 的工具注册表同风格（统一 invoke、错误转字符串不抛异常），
但每个工具内部都做了物理层约束：

    路径类   realpath 后必须在沙箱内（write/delete 的沙箱 = sandbox_workspace；
             demo 模式下 read 放宽到教程目录，用来演示"裸 Agent 越权读取"，
             但 .env 仍被物理保险丝拒绝——演示环境不把真实密钥喂给裸 Agent）
    shell    shell=False + 超时 10s；非白名单命令：
             demo 模式 → [SIMULATED]（到达执行边界但不真跑，防 rm -rf / 炸机）
             非 demo   → REJECTED

权限/审批/注入三道防线不在本文件——它们在 agent.py 编排（这样"裸 Agent"
可以只复用本文件的物理沙箱来对照）。
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from sec.permissions import ALLOWED_SHELL, PathSandbox, check_shell

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SANDBOX = ROOT / "sandbox_workspace"

SHELL_TIMEOUT = 10  # 秒（012 练习 1：超时是必须的）


class Toolbox:
    """一组绑定到沙箱的工具。invoke() 绝不抛异常，一切结果走返回值。"""

    def __init__(self, sandbox_root: str | Path | None = None, demo: bool = False):
        self.sandbox_root = Path(sandbox_root or DEFAULT_SANDBOX).resolve()
        self.sandbox_root.mkdir(parents=True, exist_ok=True)
        self.demo = demo
        # read/list：加固模式只能看沙箱；demo（裸）模式放宽到教程目录
        self.read_sandbox = PathSandbox(ROOT if demo else self.sandbox_root)
        # write/delete：两种模式都锁死在沙箱内（演示环境的物理底线）
        self.write_sandbox = PathSandbox(self.sandbox_root)

    # ---------- 注册表（function calling schema）----------

    def specs(self) -> list[dict]:
        return [
            {"type": "function", "function": {
                "name": "list_files",
                "description": "列出沙箱目录下的文件（名/大小/类型）。dir_path 默认为沙箱根目录。",
                "parameters": {"type": "object", "properties": {
                    "dir_path": {"type": "string", "description": "相对沙箱根的目录路径"}},
                    "required": []}}},
            {"type": "function", "function": {
                "name": "read_file",
                "description": "读取沙箱内的一个文本文件。",
                "parameters": {"type": "object", "properties": {
                    "path": {"type": "string", "description": "文件路径（相对沙箱根）"}},
                    "required": ["path"]}}},
            {"type": "function", "function": {
                "name": "write_file",
                "description": "向沙箱内写入/覆盖一个文本文件（write 级）。",
                "parameters": {"type": "object", "properties": {
                    "path": {"type": "string"}, "content": {"type": "string"}},
                    "required": ["path", "content"]}}},
            {"type": "function", "function": {
                "name": "delete_file",
                "description": "删除沙箱内的一个文件（destructive 级，不可逆，需人工审批）。",
                "parameters": {"type": "object", "properties": {
                    "path": {"type": "string"}},
                    "required": ["path"]}}},
            {"type": "function", "function": {
                "name": "run_shell",
                "description": ("执行只读 shell 命令（白名单: "
                               f"{sorted(ALLOWED_SHELL)}；禁止管道/重定向/出网）。"),
                "parameters": {"type": "object", "properties": {
                    "command": {"type": "string"}},
                    "required": ["command"]}}},
        ]

    def invoke(self, name: str, args: str | dict) -> dict:
        """统一入口：{"ok": bool, "result": str}。错误全部转字符串。"""
        fns = {
            "list_files": self.list_files,
            "read_file": self.read_file,
            "write_file": self.write_file,
            "delete_file": self.delete_file,
            "run_shell": self.run_shell,
        }
        fn = fns.get(name)
        if fn is None:
            return {"ok": False, "result": f"ERROR: 未知工具 {name}"}
        try:
            a = json.loads(args) if isinstance(args, str) else dict(args or {})
        except json.JSONDecodeError as e:
            return {"ok": False, "result": f"ERROR: 参数不是合法 JSON: {e}"}
        try:
            out = fn(**a)
        except TypeError as e:
            return {"ok": False, "result": f"ERROR: 参数不匹配: {e}"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "result": f"ERROR: {type(e).__name__}: {e}"}
        return {"ok": True, "result": out}

    # ---------- 工具实现 ----------

    def _resolve_read(self, path: str) -> tuple[Path | None, str | None]:
        # 物理保险丝：演示环境拒绝读取 .env（真实密钥不进对照实验）
        if self.demo and Path(str(path)).name.startswith(".env"):
            return None, "[物理保险丝] 演示环境拒绝读取 .env"
        return self.read_sandbox.resolve(path)

    def list_files(self, dir_path: str = ".") -> str:
        p, err = self.read_sandbox.resolve(dir_path or ".")
        if err:
            return f"REJECTED: {err}"
        if not p.is_dir():
            return f"ERROR: 目录不存在 {dir_path}"
        items = []
        for f in sorted(p.iterdir()):
            if f.name == "__pycache__":
                continue
            items.append({
                "name": f.name,
                "type": "dir" if f.is_dir() else "file",
                "size": f.stat().st_size if f.is_file() else "-",
            })
        return json.dumps({"dir": str(p), "items": items[:100]}, ensure_ascii=False)

    def read_file(self, path: str) -> str:
        p, err = self._resolve_read(path)
        if err:
            return f"REJECTED: {err}"
        if not p.is_file():
            return f"ERROR: 文件不存在 {path}"
        if p.stat().st_size > 200_000:
            return "ERROR: 文件过大（>200KB），拒绝读取"
        return p.read_text(encoding="utf-8", errors="replace")

    def write_file(self, path: str, content: str) -> str:
        p, err = self.write_sandbox.resolve(path)
        if err:
            return f"REJECTED: {err}"
        if p.is_dir():
            return f"ERROR: {path} 是目录"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"已写入 {p}（{len(content.encode())} 字节）"

    def delete_file(self, path: str) -> str:
        p, err = self.write_sandbox.resolve(path)
        if err:
            return f"REJECTED: {err}"
        if not p.is_file():
            return f"ERROR: 文件不存在 {path}"
        p.unlink()
        return f"已删除 {p}"

    def run_shell(self, command: str) -> str:
        """只读命令白名单 + shell=False + 超时兜底（012 练习 1 双防线）。

        demo（裸）模式：策略层（白名单/黑名单）视为"已被对照实验去掉"，
        只保留物理保险丝——非只读命令到达执行边界但不真跑（[SIMULATED]）。
        生产中这道保险丝对应容器/OS 级隔离；本教程不真执行 rm/curl 等。
        """
        verdict = check_shell(command)
        if not verdict.ok:
            if self.demo:
                return ("[SIMULATED] 演示环境不真实执行（该命令已到达执行边界）: "
                        f"{command}\n（物理保险丝兜底原因: {verdict.reason}）")
            return f"REJECTED: {verdict.reason}"
        argv = verdict.argv or []
        try:
            r = subprocess.run(
                argv, shell=False, capture_output=True, text=True,
                timeout=SHELL_TIMEOUT, cwd=str(self.sandbox_root),
            )
        except subprocess.TimeoutExpired:
            return f"ERROR: 命令超时（{SHELL_TIMEOUT}s）"
        except FileNotFoundError:
            return f"ERROR: 命令不存在 {argv[0]}"
        out = (r.stdout or "") + (r.stderr or "")
        return out[:4000] or "(无输出)"


def build_toolbox(demo: bool = False, sandbox_root: str | Path | None = None) -> Toolbox:
    """demo=True → 裸 Agent 用的放宽读取范围的物理沙箱（对照实验用）。"""
    return Toolbox(sandbox_root=sandbox_root, demo=demo)
