"""工具层：注册表 + 任务规划场景的模拟业务工具。

Agent 的本质 = LLM + 工具 + 循环。工具是 Agent 与外部世界交互的唯一通道，
本文件实现一个最小但完整的工具注册表（签名推导 JSON Schema、统一调用、
错误兜底），并提供差旅规划场景的 7 个工具。
"""
from __future__ import annotations

import ast
import hashlib
import json
import operator
from pathlib import Path
from typing import Callable, get_args, get_origin

# ---------- 注册表 ----------

_TYPE_MAP = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _json_type(anno) -> dict:
    """把 Python 类型注解翻译成 JSON Schema（LLM function calling 要求的格式）。"""
    origin = get_origin(anno)
    if origin in (list, tuple):
        item_args = get_args(anno)
        item = _json_type(item_args[0]) if item_args else {"type": "string"}
        return {"type": "array", "items": item}
    if origin is dict or anno is dict:
        return {"type": "object"}
    return {"type": _TYPE_MAP.get(anno, "string")}


class Tool:
    def __init__(self, func: Callable):
        import inspect

        self.func = func
        self.name = func.__name__
        self.description = (func.__doc__ or "").strip()
        sig = inspect.signature(func)
        props, required = {}, []
        for pname, p in sig.parameters.items():
            if pname in ("self", "cls"):
                continue
            props[pname] = _json_type(p.annotation)
            if p.default is inspect.Parameter.empty:
                required.append(pname)
        self.schema = {
            "type": "object",
            "properties": props,
            "required": required,
            "additionalProperties": False,
        }

    def to_spec(self) -> dict:
        """OpenAI function calling 的 tools 参数格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema,
            },
        }


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
        """统一调用入口：任何错误都转成结构化错误返回，绝不抛异常打断 Agent 循环。"""
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
        except Exception as e:  # noqa: BLE001
            return {"error": f"{type(e).__name__}: {e}"}
        if isinstance(result, (dict, list)):
            return {"result": result} if isinstance(result, list) else result
        return {"result": result}


# ---------- 模拟业务工具（差旅规划场景）----------
# 数据为确定性伪随机（按 输入哈希 生成），保证同一提问结果可复现

def _seed(*parts: str) -> int:
    return int(hashlib.md5("|".join(parts).encode()).hexdigest()[:8], 16)


def search_flights(origin: str, destination: str, date: str, max_price: int = 0) -> dict:
    """搜索指定日期出发的航班。返回航司、航班号、起降时间、价格（元）。"""
    airlines = [("国航", "CA"), ("东航", "MU"), ("南航", "CZ"), ("海航", "HU")]
    flights = []
    for i in range(4):
        s = _seed(origin, destination, date, str(i))
        dep_h = 7 + (s % 13)
        price = 480 + (s % 1400)
        if max_price and price > max_price:
            continue
        code, prefix = airlines[i % 4]
        flights.append({
            "airline": code,
            "flight_no": f"{prefix}{1000 + s % 8000}",
            "dep_time": f"{date} {dep_h:02d}:{(s // 13) % 6 * 10:02d}",
            "arr_time": f"{date} {dep_h + 2:02d}:{(s // 7) % 6 * 10:02d}",
            "price": price,
        })
    if not flights:
        return {"flights": [], "note": "该预算下没有航班，建议放宽 max_price"}
    return {"flights": sorted(flights, key=lambda f: f["price"])}


def search_hotels(city: str, check_in: str, check_out: str, budget_per_night: int = 0) -> dict:
    """搜索城市酒店。返回酒店名、档次、每晚价格、评分、距市中心距离。"""
    tiers = [("经济型", 0.5), ("舒适型", 1.0), ("高档型", 1.8)]
    hotels = []
    for i, (tier, mult) in enumerate(tiers):
        s = _seed(city, check_in, check_out, tier)
        price = int((260 + s % 500) * mult)
        if budget_per_night and price > budget_per_night:
            continue
        hotels.append({
            "name": f"{city}{['锦江', '全季', '希尔顿', '如家'][s % 4]}{tier}酒店",
            "tier": tier,
            "price_per_night": price,
            "rating": round(4.0 + (s % 10) / 10, 1),
            "distance_to_center_km": round(0.5 + (s % 40) / 10, 1),
        })
    return {"hotels": hotels or [], "check_in": check_in, "check_out": check_out}


def get_weather(city: str, date: str) -> dict:
    """查询城市某日天气预报。返回天气状况、最高/最低气温（℃）、降水概率。"""
    s = _seed(city, date)
    kinds = ["晴", "多云", "小雨", "阴"]
    return {
        "city": city,
        "date": date,
        "condition": kinds[s % 4],
        "high_c": 18 + s % 14,
        "low_c": 8 + s % 9,
        "precipitation_prob": (s // 4) % 100,
    }


def get_calendar() -> dict:
    """查看个人日历中的全部日程。返回日程标题与时间列表。"""
    return {"events": list(_CALENDAR)}


def add_calendar_event(title: str, start: str, duration_hours: float = 1.0) -> dict:
    """向日历添加一条日程。参数：title 日程标题，start 格式 'MM-DD HH:MM'，duration_hours 时长。"""
    event = {"title": title, "start": start, "duration_hours": duration_hours}
    _CALENDAR.append(event)
    return {"added": event, "total_events": len(_CALENDAR)}


def calc(expression: str) -> dict:
    """计算数学表达式（支持 + - * / ** 与括号）。只接受纯算术，如 '1200*3+500'。"""
    return {"value": _safe_eval(expression)}


def save_itinerary(filename: str, content: str) -> dict:
    """把行程方案保存为 output/ 目录下的 Markdown 文件。filename 需以 .md 结尾。"""
    name = Path(filename).name  # 防目录穿越
    if not name.endswith(".md") or name.startswith("."):
        return {"error": "文件名必须是普通的 .md 文件名"}
    path = Path(__file__).resolve().parent.parent / "output" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"saved_to": str(path), "bytes": len(content.encode())}


_CALENDAR: list[dict] = [
    {"title": "周一 09:30 团队周会", "start": "10-20 09:30", "duration_hours": 1.0},
    {"title": "周三 14:00 客户评审", "start": "10-22 14:00", "duration_hours": 2.0},
]

# 安全的四则运算求值：绝不使用 eval()，用 AST 只放行纯算术节点
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
    for fn in (search_flights, search_hotels, get_weather, get_calendar,
               add_calendar_event, calc, save_itinerary):
        reg.register(fn)
    return reg
