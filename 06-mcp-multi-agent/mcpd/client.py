"""MCP stdio 客户端封装：把 MCP Server 的工具接到 Agent 循环。

三件事：
  1. 连接生命周期：以子进程方式拉起 server（stdio），握手（initialize）
  2. 工具发现：list_tools() → 转成 OpenAI function-calling schema
  3. 工具调用：call_tool(name, args) → 统一转 dict（错误也不抛异常）

为什么用后台线程跑事件循环：
  Agent 主循环是同步的（openai SDK 同步客户端），而 MCP SDK 是全异步的。
  标准解法 = 专用线程常驻一个 event loop，同步侧用 run_coroutine_threadsafe
  提交协程——连接（子进程）在整个 Agent 会话期间保持复用。
"""
from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPClient:
    """异步客户端：connect → list_tools → call_tool → close。

    生命周期要点：stdio_client/ClientSession 的 async with 必须在同一个
    task 里进入和退出（anyio cancel scope 约束）。因此用一个常驻 _serve task
    持有整个上下文，其他协程只通过 self._session 发请求——请求走内存流，
    跨 task 调用是安全的。
    """

    def __init__(self, server_script: str | None = None):
        self.server_script = str(server_script or (Path(__file__).parent / "server.py"))
        self._session = None
        self._serve_task: asyncio.Task | None = None
        self._stop: asyncio.Event | None = None
        self._ready: asyncio.Event | None = None

    async def _serve(self, params: StdioServerParameters) -> None:
        """常驻任务：进入 stdio + session 上下文，保持到 close 为止。"""
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()       # JSON-RPC initialize 握手
                    self._session = session
                    self._ready.set()
                    await self._stop.wait()
        finally:
            self._session = None
            if not self._ready.is_set():
                self._ready.set()                    # 启动失败也要唤醒等待方

    async def connect(self, timeout: float = 20.0) -> None:
        """以子进程启动 server 并完成握手。"""
        params = StdioServerParameters(
            command=sys.executable,           # 用当前 venv 的解释器，别用系统 python
            args=[self.server_script],
            cwd=str(ROOT),
        )
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()
        self._serve_task = asyncio.create_task(self._serve(params))
        await asyncio.wait_for(self._ready.wait(), timeout=timeout)
        if self._session is None:
            raise RuntimeError("MCP server 启动/握手失败（检查 server.py 能否独立运行）")

    async def list_tools(self) -> list[dict]:
        """返回 MCP 工具的原始定义列表（name/description/inputSchema）。"""
        resp = await self._session.list_tools()
        return [
            {"name": t.name, "description": t.description or "",
             # mcp 1.x 字段名 inputSchema；2.x 改为 input_schema（pydantic 属性）
             "inputSchema": getattr(t, "inputSchema", None) or t.input_schema}
            for t in resp.tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict:
        """调用工具。任何失败都转成 {"error": ...}，绝不抛异常打断 Agent 循环。"""
        try:
            result = await self._session.call_tool(name, arguments or {})
        except Exception as e:  # noqa: BLE001
            return {"error": f"{type(e).__name__}: {e}"}
        # CallToolResult.content 是 TextContent/PromptMessage 等列表，取文本拼接
        texts = []
        for item in result.content:
            text = getattr(item, "text", None)
            if text is not None:
                texts.append(text)
        raw = "\n".join(texts)
        # mcp 1.x 字段名 isError；2.x 改为 is_error（pydantic 属性）
        if getattr(result, "isError", None) or getattr(result, "is_error", False):
            return {"error": raw or "未知工具错误"}
        try:
            parsed = json.loads(raw)           # 我们约定工具返回 JSON 文本
            return parsed if isinstance(parsed, dict) else {"result": parsed}
        except json.JSONDecodeError:
            return {"result": raw}

    async def close(self) -> None:
        if self._stop is not None:
            self._stop.set()                    # 通知 _serve 退出上下文
        if self._serve_task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._serve_task), timeout=10)
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                self._serve_task.cancel()
            self._serve_task = None
        self._session = None


# ---------- OpenAI schema 适配 ----------

def mcp_tools_to_openai(mcp_tools: list[dict]) -> list[dict]:
    """MCP 工具定义 → OpenAI function-calling tools 参数。

    MCP:  {name, description, inputSchema}
    FC:   {"type":"function","function":{name, description, parameters}}
    ——parameters 直接复用 inputSchema（二者都是 JSON Schema，天然兼容）。
    """
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["inputSchema"],
            },
        }
        for t in mcp_tools
    ]


class SyncMCPBridge:
    """同步门面：给同步 Agent 循环用（内部在后台线程跑 asyncio loop）。

    用法：
        bridge = SyncMCPBridge(); bridge.connect()
        specs  = mcp_tools_to_openai(bridge.list_tools())
        result = bridge.call_tool("search_kb", {"query": "团队版多少钱"})
        bridge.close()
    """

    def __init__(self, server_script: str | None = None):
        self.client = MCPClient(server_script)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def _call(self, coro, timeout: float = 30.0):
        """把协程投递到后台 loop，同步等待结果。"""
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=timeout)

    def connect(self, timeout: float = 20.0) -> None:
        self._call(self.client.connect(), timeout=timeout)

    def list_tools(self) -> list[dict]:
        return self._call(self.client.list_tools())

    def call_tool(self, name: str, arguments: dict, timeout: float = 30.0) -> dict:
        return self._call(self.client.call_tool(name, arguments), timeout=timeout)

    def close(self) -> None:
        try:
            self._call(self.client.close(), timeout=10.0)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)
            self._loop.close()
