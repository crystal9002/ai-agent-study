"""OpenAI 兼容 Chat 封装：统一接 DeepSeek/OpenAI/通义，并把 usage 记入当前 span。

judge / SUT / 生成链共用这一个出口，token 与成本归因才能完整落进 Trace。
"""
from __future__ import annotations

import os

from llmops.trace import Trace

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(
            base_url=os.getenv("OPENAI_BASE_URL"),
            api_key=os.getenv("OPENAI_API_KEY"),
        )
    return _client


def chat(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.2,
    tools: list[dict] | None = None,
    trace: Trace | None = None,
    max_tokens: int | None = None,
):
    """非流式 chat。返回 SDK message；有 trace 时自动 add_usage 记到当前 span。"""
    model = model or os.getenv("LLM_MODEL", "deepseek-chat")
    kwargs: dict = {"model": model, "messages": messages, "temperature": temperature}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    resp = _get_client().chat.completions.create(**kwargs)
    if trace is not None and resp.usage:
        trace.add_usage(resp.usage.prompt_tokens or 0, resp.usage.completion_tokens or 0, model)
    if getattr(resp, "usage", None):
        chat.last_usage = {
            "model": model,
            "prompt": resp.usage.prompt_tokens or 0,
            "completion": resp.usage.completion_tokens or 0,
        }
    else:
        chat.last_usage = None
    return resp.choices[0].message


chat.last_usage = None


def chat_with_usage(messages: list[dict], **kwargs) -> tuple[object, dict | None]:
    """同 chat()，但返回 (message, usage_dict) —— 供外部上报（如 Langfuse）使用。"""
    msg = chat(messages, **kwargs)
    return msg, chat.last_usage
