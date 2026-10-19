"""LLM 调用：OpenAI 兼容 Chat API，支持流式。

可对接：OpenAI / DeepSeek / 通义千问 / 火山方舟 / vLLM 自建服务等，
只需改 .env 里的 OPENAI_BASE_URL / OPENAI_API_KEY。
"""
from __future__ import annotations

import os
from collections.abc import Iterator


def build_messages(system: str, user: str) -> list[dict]:
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


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
        self.model = model or os.getenv("LLM_MODEL", "gpt-4o-mini")
        self.temperature = temperature

    def chat_stream(self, system: str, user: str) -> Iterator[str]:
        """流式输出 token，生成环节用（首字延迟低，体验好）。"""
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=build_messages(system, user),
            temperature=self.temperature,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    def chat(self, system: str, user: str) -> str:
        return "".join(self.chat_stream(system, user))
