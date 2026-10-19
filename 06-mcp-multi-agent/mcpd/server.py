"""MCP Server（FastMCP · stdio 传输）：本教程的"被接入方"。

一个 Server 暴露给客户端的 3 个契约（写代码前先想清楚这三件事）：

  ① 工具清单契约（tools/list）
     客户端随时可以问"你有哪些工具"。每个工具必须有稳定的 name、
     人类可读的 description——description 会直接进入 LLM 提示词，
     写得好不好决定模型会不会选对工具。

  ② 参数契约（inputSchema）
     由函数签名 + 类型注解 + docstring 自动推导为 JSON Schema。
     客户端/LLM 严格按这个 schema 生成参数；服务端校验失败要返回
     结构化错误（而不是让进程崩溃——stdio server 崩了客户端就断连）。

  ③ 结果契约（call_tool 返回）
     返回统一为「一段文本内容」（实践中通常放 JSON 字符串）。
     客户端拿到后自行决定回填给 LLM 还是解析展示。
     业务错误也走返回值（{"error": ...}），不要抛裸异常。

运行：
    python mcpd/server.py        # stdio：等待父进程通过 stdin/stdout 说 JSON-RPC
日志纪律：stdio 传输下 stdout 是协议通道！任何 print/logging 都必须走 stderr，
否则会污染 JSON-RPC 帧导致握手失败（FastMCP 内部已把日志走 stderr）。
"""
from __future__ import annotations

import ast
import operator
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

import sys
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from mcpd.kb import search_kb as _kb_search  # noqa: E402

mcp = FastMCP(
    "study-demo",
    instructions="演示用知识库服务：查产品定价 FAQ、安全计算、看时间、存笔记。",
)

# notes/ 目录：save_note 的落盘位置（相对本教程文件夹根）
_NOTES_DIR = Path(__file__).resolve().parent.parent / "notes"


# ---------- 安全求值（与 02 教程同思路：AST 白名单，绝不 eval） ----------
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow}
_UNA = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _safe_eval(expr: str):
    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            return _BIN[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNA:
            return _UNA[type(node.op)](walk(node.operand))
        raise ValueError(f"不支持的表达式元素: {type(node).__name__}")
    return walk(ast.parse(expr, mode="eval"))


# ---------- 4 个工具：每个函数 = 一份对外契约 ----------

@mcp.tool()
def search_kb(query: str, top_k: int = 2) -> dict:
    """检索产品知识库（定价/功能/折扣 FAQ）。query 用中文关键词，如'团队版多少钱'。"""
    try:
        return _kb_search(query, top_k=max(1, min(int(top_k), 5)))
    except Exception as e:  # 业务错误走返回值，不炸进程
        return {"error": f"{type(e).__name__}: {e}"}


@mcp.tool()
def calc(expression: str) -> dict:
    """计算数学表达式（+ - * / ** 与括号），如 '29*50*12'。只接受纯算术。"""
    try:
        return {"expression": expression, "value": _safe_eval(expression)}
    except ZeroDivisionError:
        return {"error": "除零错误"}
    except Exception as e:
        return {"error": f"表达式不合法: {e}"}


@mcp.tool()
def get_time() -> dict:
    """获取服务器当前时间（本地时区）。"""
    now = datetime.now()
    return {"time": now.strftime("%Y-%m-%d %H:%M:%S"), "weekday": "一二三四五六日"[now.weekday()]}


@mcp.tool()
def save_note(filename: str, content: str) -> dict:
    """把一段文本保存为 notes/ 目录下的 .md 笔记。filename 必须是普通 .md 文件名。"""
    name = Path(filename).name  # 防目录穿越：只取最后一段
    if not name.endswith(".md") or name.startswith("."):
        return {"error": "文件名必须是普通的 .md 文件名（如 note.md）"}
    _NOTES_DIR.mkdir(parents=True, exist_ok=True)
    path = _NOTES_DIR / name
    path.write_text(content, encoding="utf-8")
    return {"saved_to": str(path), "chars": len(content)}


if __name__ == "__main__":
    mcp.run(transport="stdio")  # 阻塞：读 stdin 的 JSON-RPC，写 stdout
