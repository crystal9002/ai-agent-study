"""LLM 封装：OpenAI 兼容 Chat + Function Calling。

对接任意兼容服务：OpenAI / DeepSeek / 通义 / 火山方舟 / vLLM，改 .env 即可。
（与 02 教程 agent/llm.py 同款，可对照阅读。）
"""
from __future__ import annotations

import os


class LLM:
    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.2,
    ):
        from openai import OpenAI

        self.client = OpenAI(
            base_url=base_url or os.getenv("OPENAI_BASE_URL"),
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
        )
        self.model = model or os.getenv("LLM_MODEL", "deepseek-chat")
        self.temperature = temperature

    def chat(self, messages: list[dict], tools: list[dict] | None = None):
        """返回 ChatCompletionMessage；tools 不为空时模型可能返回 tool_calls。"""
        kwargs: dict = {"model": self.model, "messages": messages,
                        "temperature": self.temperature}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message

    @staticmethod
    def to_message(msg) -> dict:
        """把 SDK 消息对象转成可回传给 API 的 dict（必须保留 tool_calls）。"""
        d: dict = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            d["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name,
                              "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]
        return d
