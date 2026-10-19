# 03 客户端接入：把 MCP 工具桥进 Agent

> 上一课：[02 写一个 MCP server](02-write-mcp-server.md) | 下一课：[04 手写多智能体](04-multi-agent.md)
> 对应代码：`mcpd/client.py` `scripts/02_mcp_agent.py`

03 概念课的代码骨架是"30 行连上 server 列工具"。本篇把剩下的半句补完：
**怎么让这些工具进入你手写的 Function Calling 循环，并且工程上稳**。

## 1. 客户端要做的四件事

```
┌─ 客户端（mcpd/client.py）────────────────────────────────┐
│ ① connect    子进程拉起 server + initialize 握手           │
│ ② list_tools 拿 {name, description, inputSchema}          │
│ ③ 适配       MCP schema → OpenAI FC tools 参数            │
│ ④ call_tool  执行 + 结果归一化成 dict（错误不抛）          │
└──────────────────────────────────────────────────────────┘
```

## 2. 子进程生命周期：连接必须"养"在常驻 task 里

`stdio_client(params)` 会 `subprocess.Popen` 拉起 server，并用管道对接 stdin/stdout。
工程上有两个真实的坑（我们都踩过）：

**坑 1：anyio cancel scope 不能跨 task 退出。**
最初版本把 `async with stdio_client(...)` 存进 `AsyncExitStack`，在"连接协程"里进入、
在"关闭协程"里退出——运行时报 `Attempted to exit cancel scope in a different task`。
修法：一个**常驻 `_serve` task** 持有全部上下文，其他协程只通过 `self._session` 发请求
（请求走内存流，跨 task 安全）；`close()` 只需要 set 一个 Event 让 `_serve` 自己退出：

```python
async def _serve(self, params):
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            self._session = session
            self._ready.set()
            await self._stop.wait()      # close() 时被唤醒 → 顺序退出上下文
```

**坑 2：同步 Agent 循环 × 全异步 SDK。**
Agent 主循环用的是 openai 同步客户端，MCP SDK 是 asyncio 的。`SyncMCPBridge` 的解法：
后台线程常驻一个 event loop，同步侧用 `asyncio.run_coroutine_threadsafe` 投递协程并
`.result(timeout)` 等待。连接在整个会话期间复用——**不要每次调工具都新建连接**，
stdio 握手 + 子进程启动的开销会吃掉延迟预算。

## 3. list_tools → FC schema：一次几乎免费的转换

```python
def mcp_tools_to_openai(mcp_tools):
    return [{
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["inputSchema"],   # 直接复用：两者都是 JSON Schema
        }
    } for t in mcp_tools]
```

为什么能直接复用：OpenAI 的 `parameters` 与 MCP 的 `inputSchema` 都遵循 JSON Schema，
字段一一对应。唯一要注意的是 MCP schema 可能带 `additionalProperties`/嵌套 `$defs`，
DeepSeek 等兼容模型对复杂 schema 支持不一——server 端把参数设计扁平（顶层几个标量）最稳。

## 4. 工具结果回填：错误也是信息

```python
result = bridge.call_tool(name, args)          # 永远返回 dict，不抛异常
messages.append({
    "role": "tool", "tool_call_id": tc.id,
    "content": json.dumps(result, ensure_ascii=False),
})
```

三层错误都被归一成 `{"error": ...}`：
1. **传输层**：`call_tool` 包 try/except（子进程死了、超时）
2. **协议层**：`result.isError=True`（server 报 protocol/工具错误）
3. **内容层**：工具按约定返回 `{"error": ...}` 的业务错误

回填后模型的典型行为：换参数重试、或把原因如实告诉用户。**Agent 循环的健壮性 =
"工具错误永远以数据形式回到上下文"，而不是以异常打断循环。**

## 5. Agent 循环本体：与 02 教程 executor 同构

`scripts/02_mcp_agent.py` 的循环没有新魔法：

```python
for it in range(1, MAX_ITERS + 1):
    msg = llm.chat(messages, tools=fc_tools)
    if not msg.tool_calls:
        return msg.content            # 模型不再调工具 → 结束
    for tc in msg.tool_calls:         # Act + Observe
        result = bridge.call_tool(tc.function.name, json.loads(tc.function.arguments))
        messages.append({"role": "tool", ...})
```

**MCP 接入没有改变循环本身**——它只替换了 ① tools 的来源（本地注册表 → 远端 list_tools）
和 ② 工具执行函数（本地调用 → call_tool）。这就是 003 课说的"循环一行不用改"。

## 6. 动手验证

```bash
.venv/bin/python scripts/02_mcp_agent.py "50人团队版一年多少钱？"
# 🔌 已通过 MCP 发现 4 个工具: search_kb, calc, get_time, save_note
#   [iter 1] 🔧 MCP 调用 → search_kb({"query": "团队版 定价 …"})
#   [iter 2] 🔧 MCP 调用 → calc({"expression": "29*50*12"})  ↩ {"value": 17400}
# 💬 最终回答: … 17,400 元（年付 8.5 折 14,790 元）…
# 🔌 MCP 子进程已关闭
```

## 思考题

1. 为什么建议整个会话复用一条 MCP 连接，而不是每次工具调用都开关子进程？
2. `tc.function.arguments` 是字符串，为什么要 `json.loads` 后再传给 `call_tool`？
3. 如果 server 端工具新增了一个（如 `list_notes`），客户端代码要改哪些地方？

### 参考答案

1. stdio 连接的成本包括：子进程 fork/exec、Python 解释器启动、import 全部依赖、JSON-RPC initialize 往返——本地也要几十到几百毫秒；Agent 一次任务常调 3~10 次工具，每次重连会把延迟放大一个数量级。另外 server 内的内存态（如 `save_note` 已写的笔记、缓存）在重连后丢失。
2. MCP `call_tool(name, arguments: dict)` 接受的是 dict；而 OpenAI 协议里 `tool_calls[].function.arguments` 是**JSON 字符串**（模型生成的原文）。必须解析后传入；解析失败要兜底 `args={}` 并让工具返回参数错误，而不是让 `json.loads` 的异常炸掉循环。
3. 零改动。客户端是数据驱动的：`list_tools` 每次连接后重新发现，`mcp_tools_to_openai` 动态转换。这正是 MCP 相对硬编码工具列表的价值——server 加工具，所有客户端下次连接自动看见。唯一例外：若 Agent 的 system prompt 里手写了工具使用说明，则需同步更新提示词。

---

*上一课：[02 写一个 MCP server](02-write-mcp-server.md) | 下一课：[04 手写多智能体](04-multi-agent.md)*
