"""WorkerAgent：每个 worker = 独立上下文 + 专属 system prompt + 工具子集。

与单 Agent 的本质区别（呼应 006 课）：
  - 上下文隔离：worker 只看到 supervisor 分派的任务文本，
    看不到全局对话历史 → 不同任务的背景知识互不污染
  - 权限分立：worker 只挂自己需要的工具（检索 worker 拿不到写文件权限）
  - 每个 worker 内部仍是标准 ReAct 循环（thinking → tool → observe → …）

三个演示 worker：
  researcher（检索）→ 只有 search_kb
  calculator（计算）→ 只有 calc
  writer（写作）    → 只有 save_note（写 output/ 下的文件）
"""
from __future__ import annotations

import ast
import json
import operator
from pathlib import Path
from typing import Callable

from multi.bus import EventBus
from mcpd.kb import search_kb

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"

# ---------- worker 的工具（本地实现，与 MCP server 同逻辑、独立裁剪） ----------

def _tool_calc(expression: str) -> dict:
    """计算数学表达式（+ - * / ** 与括号）。"""
    bins = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
            ast.Div: operator.truediv, ast.Pow: operator.pow}
    unas = {ast.UAdd: operator.pos, ast.USub: operator.neg}

    def walk(n):
        if isinstance(n, ast.Expression):
            return walk(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in bins:
            return bins[type(n.op)](walk(n.left), walk(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in unas:
            return unas[type(n.op)](walk(n.operand))
        raise ValueError(f"不支持: {type(n).__name__}")
    return {"value": walk(ast.parse(expression, mode="eval"))}


def _tool_save(filename: str, content: str) -> dict:
    """保存 Markdown 文件到 output/ 目录。filename 需以 .md 结尾。"""
    name = Path(filename).name
    if not name.endswith(".md") or name.startswith("."):
        return {"error": "文件名必须是普通的 .md 文件名"}
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / name
    path.write_text(content, encoding="utf-8")
    return {"saved_to": str(path), "chars": len(content)}


# 工具注册表：{name: (函数, 参数说明)}
WORKER_TOOLS: dict[str, dict] = {
    "search_kb": {"fn": search_kb, "desc": "query(关键词), top_k(条数,默认2)"},
    "calc": {"fn": _tool_calc, "desc": "expression(算术表达式,如 '29*50*12')"},
    "save": {"fn": _tool_save, "desc": "filename(xxx.md), content(Markdown 全文)"},
}


def _invoke(name: str, args: dict) -> dict:
    tool = WORKER_TOOLS.get(name)
    if tool is None:
        return {"error": f"未知工具: {name}"}
    try:
        result = tool["fn"](**args)
    except TypeError as e:
        return {"error": f"参数不匹配: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    return result if isinstance(result, dict) else {"result": result}


# ---------- Worker 定义 ----------

WORKER_SYSTEM = {
    "researcher": (
        "你是检索专家。只使用 search_kb 工具查询知识库，基于真实返回整理事实，"
        "不编造。输出：关键事实列表（含数字），不超过 8 行。"
    ),
    "calculator": (
        "你是计算专家。只使用 calc 工具做算术。先列出算式再调用工具，"
        "基于返回值给出结论（含单位/口径），不超过 5 行。"
    ),
    "writer": (
        "你是写作专家。只基于给定素材用 save 工具写 Markdown 文件，"
        "不添加素材之外的事实。文件含标题、要点、数据表。完成后报告保存路径。"
    ),
}

WORKER_TOOLSET: dict[str, list[str]] = {
    "researcher": ["search_kb"],
    "calculator": ["calc"],
    "writer": ["save"],
}


class WorkerAgent:
    """单个 worker：迷你 ReAct 循环（与 02 教程 executor 同构，精简版）。"""

    def __init__(self, name: str, bus: EventBus, max_iters: int = 5,
                 on_tool: Callable[[dict], None] | None = None):
        self.name = name
        self.bus = bus
        self.max_iters = max_iters
        self.on_tool = on_tool          # 工具调用明细回调（supervisor 收集用）
        self.system = WORKER_SYSTEM[name]
        self.tool_names = WORKER_TOOLSET[name]

    def _tool_specs(self) -> list[dict]:
        """给 LLM 看的工具描述（极简版 schema，够 DeepSeek 用）。"""
        return [
            {"name": n, "description": WORKER_TOOLS[n]["desc"]}
            for n in self.tool_names
        ]

    def run(self, task: str, llm) -> str:
        """执行一个分派任务，返回结论文本。全程事件可观测。
        （supervisor 已在总线上发过 dispatch 消息，这里不再重复发）"""
        tool_log: list[dict] = []
        # worker 独立上下文：只有 system + 本次任务
        messages: list[dict] = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": task},
        ]
        tools_text = json.dumps(self._tool_specs(), ensure_ascii=False)

        for _ in range(self.max_iters):
            # 工具以"文本协议"传给模型（避免对 tool-calling 格式过度依赖，
            # 也让本文件自包含、不依赖 openai SDK 的结构化参数）
            prompt = messages + [
                {"role": "user",
                 "content": f"可用工具(JSON): {tools_text}\n"
                            "如需调用工具，单独输出一行 JSON："
                            '{"tool": "工具名", "args": {...}}；'
                            "否则直接输出最终结论。"}
            ]
            reply = (llm.chat(prompt).content or "").strip()
            call = _parse_tool_call(reply)

            if call is None:
                # 无工具调用 → 视为最终结论
                self.bus.send(self.name, "*", reply or "（无输出）",
                              tool_events=tool_log)
                return reply or "（worker 未返回结论）"

            name, args = call
            result = _invoke(name, args)
            event = {"worker": self.name, "tool": name, "args": args, "result": result}
            tool_log.append(event)
            if self.on_tool:
                self.on_tool(event)
            self.bus.send(self.name, f"tool:{name}",
                          json.dumps(result, ensure_ascii=False)[:300])
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user",
                             "content": f"工具 {name} 返回: "
                                        f"{json.dumps(result, ensure_ascii=False)}\n"
                                        "继续：要么再调用工具，要么输出最终结论。"})

        msg = f"（失败：超过最大轮数 {self.max_iters}）"
        self.bus.send(self.name, "*", msg, tool_events=tool_log)
        return msg


def _parse_tool_call(text: str) -> tuple[str, dict] | None:
    """从模型输出中提取工具调用 JSON（容忍围栏/闲话/一次输出多行——取第一个能解析的）。"""
    text = text.strip()
    if "```" in text:                      # 去掉代码围栏
        parts = text.split("```")
        for p in parts:
            p = p.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            if p.startswith("{"):
                text = p
                break
    # 逐行 + 整体扫描：找到第一个能成功解析出 {tool, args} 的 JSON 对象
    candidates = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("{")]
    candidates.append(text)
    for cand in candidates:
        start, end = cand.find("{"), cand.rfind("}")
        if start == -1 or end <= start:
            continue
        try:
            obj = json.loads(cand[start:end + 1])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "tool" in obj:
            return str(obj["tool"]), dict(obj.get("args") or {})
    return None


def make_workers(bus: EventBus, on_tool=None) -> dict[str, WorkerAgent]:
    """构造默认三件套。"""
    return {
        name: WorkerAgent(name, bus, on_tool=on_tool)
        for name in ("researcher", "calculator", "writer")
    }
