"""LLM 封装：OpenAI 兼容 Chat（对接 DeepSeek / 通义 / 火山方舟 / OpenAI，改 .env 即可）。

与 02-agent-tutorial/agent/llm.py 同构，精简版：
  - chat(messages) 单轮补全
  - chat_json(messages) 强制产出 JSON（剥围栏 + 容错解析）
"""
from __future__ import annotations

import json
import os
import re


class LLM:
    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.2,
    ):
        from openai import OpenAI

        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "缺少 OPENAI_API_KEY：请检查教程根目录 .env 是否已配置（参考 .env.example）")
        self.client = OpenAI(
            base_url=base_url or os.getenv("OPENAI_BASE_URL"),
            api_key=key,
        )
        self.model = model or os.getenv("LLM_MODEL", "deepseek-chat")
        self.temperature = temperature

    def chat(self, messages: list[dict], tools: list[dict] | None = None):
        """返回 ChatCompletionMessage。tools 非空时模型可能返回 tool_calls。"""
        kwargs: dict = {"model": self.model, "messages": messages,
                        "temperature": self.temperature}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message

    def chat_json(self, messages: list[dict], max_retries: int = 2) -> dict:
        """要求模型输出 JSON 对象并解析（剥 ``` 围栏；失败重试）。"""
        msgs = messages + [
            {"role": "user", "content": "只输出一个 JSON 对象，不要任何其他文字。"}
        ]
        last_err = None
        for _ in range(max_retries + 1):
            text = (self.chat(msgs).content or "").strip()
            obj = _extract_json(text)
            if obj is not None:
                return obj
            last_err = text[:200]
            msgs.append({"role": "assistant", "content": text})
            msgs.append({"role": "user",
                         "content": "上面不是合法 JSON，请重新只输出 JSON 对象。"})
        raise ValueError(f"LLM 多次未返回合法 JSON，最后输出: {last_err}")

    @staticmethod
    def to_message(msg) -> dict:
        """SDK 消息对象 → 可回传的 dict（保留 tool_calls）。"""
        d: dict = {"role": "assistant", "content": msg.content or ""}
        if getattr(msg, "tool_calls", None):
            d["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name,
                              "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]
        return d


def _extract_json(text: str) -> dict | None:
    """从文本中抠出第一个 JSON 对象。"""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(text[start:end + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None
