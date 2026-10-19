"""工具层：注册表 + 知识库助手场景的 4 个工具。

Agent 的本质 = LLM + 工具 + 循环。本文件复用 02 教程的最小工具注册表思路
（签名自动推 JSON Schema、统一调用、错误兜底），工具集换成"查知识库"场景：

    search_kb    检索知识库（01 教程 RAG 检索能力的 Agent 工具化封装）
    calc         安全四则运算（组合任务里的"算账"）
    write_note   把结论写进 output/ 下的笔记文件
    list_notes   列出已有笔记
"""
from __future__ import annotations

import ast
import json
import operator
from pathlib import Path
from typing import Callable, get_args, get_origin

from . import kb

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

# ---------- 注册表（签名 → JSON Schema） ----------

_TYPE_MAP = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _json_type(anno) -> dict:
    """把 Python 类型注解翻译成 function calling 要求的 JSON Schema。"""
    origin = get_origin(anno)
    if origin in (list, tuple):
        args = get_args(anno)
        return {"type": "array", "items": _json_type(args[0]) if args else {"type": "string"}}
    if origin is dict or anno is dict:
        return {"type": "object"}
    return {"type": _TYPE_MAP.get(anno, "string")}


class Tool:
    def __init__(self, func: Callable):
        import inspect

        self.func = func
        self.name = func.__name__
        self.description = (func.__doc__ or "").strip()
        props, required = {}, []
        for pname, p in inspect.signature(func).parameters.items():
            props[pname] = _json_type(p.annotation)
            if p.default is inspect.Parameter.empty:
                required.append(pname)
        self.schema = {"type": "object", "properties": props,
                       "required": required, "additionalProperties": False}

    def to_spec(self) -> dict:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description,
                             "parameters": self.schema}}


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, func: Callable) -> Callable:
        t = Tool(func)
        self._tools[t.name] = t
        return func

    def specs(self) -> list[dict]:
        return [t.to_spec() for t in self._tools.values()]

    def invoke(self, name: str, arguments: str | dict) -> dict:
        """统一调用入口：任何错误都转成 {"error": ...} 回填，绝不打断 Agent 循环。"""
        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"未知工具: {name}"}
        try:
            args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
        except json.JSONDecodeError as e:
            return {"error": f"参数不是合法 JSON: {e}"}
        try:
            result = tool.func(**args)
        except TypeError as e:
            return {"error": f"参数不匹配: {e}"}
        except Exception as e:  # noqa: BLE001 —— 含索引缺失、模型未建库等
            return {"error": f"{type(e).__name__}: {e}"}
        return result if isinstance(result, dict) else {"result": result}


# ---------- 知识库助手工具 ----------

def search_kb(query: str, k: int = 3) -> dict:
    """检索企业知识库（产品手册/价格FAQ/API 文档）。参数：query 自然语言问题，
    k 返回条数（默认 3，上限 10）。返回 results 列表，每项含 n（引用编号）、
    doc（来源文档）、title（章节）、text（片段）。回答涉及产品、价格、接口的事实
    必须基于返回内容，并在句末标注来源编号，如 [1]；返回空列表说明知识库没有相关信息。"""
    try:
        k = max(1, min(int(k), 10))      # 模型偶尔把 k 传成 "5" 这样的字符串
    except (TypeError, ValueError):
        k = 3
    results = kb.search(query, k=k)
    if not results:
        return {"results": [], "note": "知识库中没有相关信息，回答时请如实说明"}
    return {"results": results, "count": len(results)}


def calc(expression: str) -> dict:
    """计算数学表达式（支持 + - * / ** 与括号）。只接受纯算术，如 '240*50'。"""
    return {"value": _safe_eval(expression)}


def write_note(filename: str, content: str) -> dict:
    """把结论保存为 output/ 目录下的 Markdown 笔记。filename 需以 .md 结尾，
    content 为完整 Markdown 正文。"""
    name = Path(filename).name            # 剥离目录，防路径穿越
    if not name.endswith(".md") or name.startswith("."):
        return {"error": "文件名必须是普通的 .md 文件名"}
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / name
    path.write_text(content, encoding="utf-8")
    return {"saved_to": str(path), "bytes": len(content.encode("utf-8"))}


def list_notes() -> dict:
    """列出 output/ 目录下已保存的笔记文件名（不递归子目录）。"""
    if not OUTPUT_DIR.exists():
        return {"notes": []}
    return {"notes": sorted(p.name for p in OUTPUT_DIR.glob("*.md"))}


# 安全求值：绝不 eval()，用 AST 只放行纯算术节点
_BIN_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
            ast.Div: operator.truediv, ast.Pow: operator.pow}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _safe_eval(expr: str):
    def _walk(node):
        if isinstance(node, ast.Expression):
            return _walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            return _BIN_OPS[type(node.op)](_walk(node.left), _walk(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            return _UNARY_OPS[type(node.op)](_walk(node.operand))
        raise ValueError(f"不支持的表达式元素: {ast.dump(node)}")

    return _walk(ast.parse(expr, mode="eval"))


def register_default_tools() -> ToolRegistry:
    reg = ToolRegistry()
    for fn in (search_kb, calc, write_note, list_notes):
        reg.register(fn)
    return reg
