"""Span 级追踪器：给 LLM 应用的每个环节（检索/生成/工具/裁判）打点落盘。

核心概念（对应 docs/04-tracing.md）：
- Trace  = 一次完整运行（run_id），内部是一棵 Span 树
- Span   = 一个有名字的环节（retrieve / generate / judge / tool_xxx…），
           记录 inputs(截断) / output(截断) / tokens / latency / error / 成本
- 落盘格式 = runs/<run_id>.jsonl（首行 meta + 每行一个 span），供 05_web 仪表盘读取

用法：
    tr = Trace("rag_demo", meta={"model": "deepseek-chat"})
    @tr.record_span("retrieve")
    def retrieve(q: str): ...
    tr.add_usage(prompt_tokens, completion_tokens)   # 在被包裹函数内部调用，记到当前 span
    tr.finish()                                      # 返回 run 记录 dict

成本估算：内置常见模型价目表（美元/百万 token），可用环境变量
PRICE_IN_PER_M / PRICE_OUT_PER_M 整体覆盖，或在 .env 里按模型名覆盖。
"""
from __future__ import annotations

import contextvars
import functools
import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterator

# ---------- 成本价目表（美元 / 百万 token，(输入, 输出)）----------
PRICE_TABLE: dict[str, tuple[float, float]] = {
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "qwen-plus": (0.40, 1.20),
}

# 截断长度（避免落盘文件爆炸）
_INPUT_TRUNC = 200
_OUTPUT_TRUNC = 400


def _truncate(v: Any, limit: int) -> str:
    """把任意值转成截断后的字符串表示。"""
    if v is None:
        return ""
    if not isinstance(v, str):
        try:
            v = json.dumps(v, ensure_ascii=False)
        except (TypeError, ValueError):
            v = str(v)
    return v if len(v) <= limit else v[:limit] + f"…[截断,共{len(v)}字符]"


def estimate_cost_usd(model: str | None, prompt_tokens: int, completion_tokens: int) -> float:
    """按价目表估算一次 LLM 调用的成本（USD）。"""
    import os

    pin = os.getenv("PRICE_IN_PER_M")
    pout = os.getenv("PRICE_OUT_PER_M")
    if pin and pout:
        rate_in, rate_out = float(pin) / 1e6, float(pout) / 1e6
    else:
        # 价目表单位是"美元/百万 token"，换算成"美元/token"
        per_m_in, per_m_out = PRICE_TABLE.get(model or "", (0.0, 0.0))
        rate_in, rate_out = per_m_in / 1e6, per_m_out / 1e6
    return round(prompt_tokens * rate_in + completion_tokens * rate_out, 6)


@dataclass
class Span:
    """一个环节的执行记录。"""

    span_id: str
    parent_id: str | None
    name: str
    inputs: str = ""
    output: str = ""
    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    error: str | None = None
    cost_usd: float = 0.0
    extra: dict = field(default_factory=dict)

    def add_usage(self, prompt_tokens: int = 0, completion_tokens: int = 0, model: str | None = None) -> None:
        """在 span 内部补充 token 用量与模型名（成本随之重算）。"""
        self.prompt_tokens += int(prompt_tokens or 0)
        self.completion_tokens += int(completion_tokens or 0)
        if model:
            self.model = model
        self.cost_usd = estimate_cost_usd(self.model, self.prompt_tokens, self.completion_tokens)


# 当前打开的 span 栈（上下文变量，线程/协程安全；本教程单线程够用）
_span_stack: contextvars.ContextVar[list[Span]] = contextvars.ContextVar("span_stack", default=[])


class Trace:
    """一次运行的追踪容器。"""

    def __init__(self, name: str, meta: dict | None = None):
        self.run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.name = name
        self.meta = meta or {}
        self.started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self.spans: list[Span] = []
        self._stack: list[Span] = []
        self._t0 = time.perf_counter()

    # ---------- span 上下文 ----------
    @contextmanager
    def span(self, name: str, inputs: Any = None, **extra: Any) -> Iterator[Span]:
        """with trace.span("retrieve", query) as sp: ... —— 自动记 latency/error/父子关系。"""
        parent = self._stack[-1].span_id if self._stack else None
        sp = Span(
            span_id=uuid.uuid4().hex[:10],
            parent_id=parent,
            name=name,
            inputs=_truncate(inputs, _INPUT_TRUNC),
            extra=extra or {},
        )
        self._stack.append(sp)
        token = _span_stack.set(_span_stack.get() + [sp])
        t0 = time.perf_counter()
        try:
            yield sp
        except Exception as e:  # noqa: BLE001 —— 记录后原样抛出，不吞错
            sp.error = f"{type(e).__name__}: {e}"
            raise
        finally:
            sp.latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            self._stack.pop()
            _span_stack.reset(token)
            self.spans.append(sp)

    def record_span(self, name: str, fn: Callable | None = None):
        """装饰器形态：@trace.record_span("retrieve")。

        既可直接装饰函数，也可先记 inputs 动态取值（fn 第一个参数视为主要输入）。
        """
        if fn is not None:  # 直接传函数的形态 record_span(name, fn)
            return self._wrap(name, fn)

        def deco(f: Callable) -> Callable:
            return self._wrap(name, f)

        return deco

    def _wrap(self, name: str, fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            main_input = args[0] if args else None
            with self.span(name, inputs=main_input):
                return fn(*args, **kwargs)

        return wrapper

    # ---------- token 用量 ----------
    def add_usage(self, prompt_tokens: int = 0, completion_tokens: int = 0, model: str | None = None) -> None:
        """把 token 用量记到栈顶 span（通常在 LLM 调用后立即调用）。"""
        stack = _span_stack.get()
        if stack:
            stack[-1].add_usage(prompt_tokens, completion_tokens, model)
        elif self._stack:  # 兜底：上下文变量异常时用实例栈
            self._stack[-1].add_usage(prompt_tokens, completion_tokens, model)

    # ---------- 汇总 ----------
    @property
    def total_tokens(self) -> int:
        return sum(s.prompt_tokens + s.completion_tokens for s in self.spans)

    @property
    def total_cost_usd(self) -> float:
        return round(sum(s.cost_usd for s in self.spans), 6)

    @property
    def total_latency_ms(self) -> float:
        return round((time.perf_counter() - self._t0) * 1000, 2)

    def finish(self) -> dict:
        """结束运行，返回可落盘的 run 记录（meta + spans + 汇总）。"""
        return {
            "run_id": self.run_id,
            "name": self.name,
            "started_at": self.started_at,
            "meta": self.meta,
            "summary": {
                "span_count": len(self.spans),
                "total_tokens": self.total_tokens,
                "total_cost_usd": self.total_cost_usd,
                "total_latency_ms": self.total_latency_ms,
                "error_count": sum(1 for s in self.spans if s.error),
            },
            "spans": [asdict(s) for s in self.spans],
        }

    def report_text(self) -> str:
        """终端友好的 span 树报告（按父子缩进）。"""
        by_parent: dict[str | None, list[Span]] = {}
        for s in self.spans:
            by_parent.setdefault(s.parent_id, []).append(s)
        lines: list[str] = []
        lines.append(f"═══ Trace {self.run_id} · {self.name} ═══")

        def walk(parent: str | None, depth: int) -> None:
            for s in by_parent.get(parent, []):
                flag = " ❌" + s.error if s.error else ""
                tok = f" {s.prompt_tokens}+{s.completion_tokens}tok" if s.prompt_tokens or s.completion_tokens else ""
                cost = f" ${s.cost_usd:.4f}" if s.cost_usd else ""
                lines.append(
                    f"{'  ' * depth}├─ {s.name}  {s.latency_ms:.0f}ms{tok}{cost}{flag}"
                )
                if s.inputs:
                    lines.append(f"{'  ' * depth}│    入参: {s.inputs[:80]}")
                if s.output:
                    lines.append(f"{'  ' * depth}│    出参: {s.output[:80]}")
                walk(s.span_id, depth + 1)

        walk(None, 0)
        lines.append(
            f"─── 合计: {len(self.spans)} spans · {self.total_tokens} tokens · "
            f"${self.total_cost_usd:.4f} · {self.total_latency_ms:.0f}ms ───"
        )
        return "\n".join(lines)
