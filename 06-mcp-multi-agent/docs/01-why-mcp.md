# 01 为什么需要 MCP

> 上一课（概念）：[AI-Agent开发教程 003 MCP协议](../../AI-Agent开发教程/003-MCP协议.md)
> 下一课：[02 写一个 MCP server](02-write-mcp-server.md)

本篇不重复 003 课的概念，只解决一个问题：**为什么值得花半天学会自己写 MCP server**。

## 1. 没有 MCP：N×M 集成地狱

假设你要把"文件系统、数据库、浏览器、Slack"四种工具，接到"你的 Agent、Claude Desktop、
Cursor、内部评测平台"四个应用里：

```
没有协议时：每个应用 × 每个工具 = 一套专属集成代码
  你的Agent ──自定义代码──► 文件系统
  你的Agent ──自定义代码──► 数据库
  Claude   ──另一套代码──► 文件系统     ← 重复！
  Cursor   ──又一套代码──► 数据库       ← 又重复！
  …… 4 × 4 = 16 条集成路径，改一个工具接口要改四处
```

每个集成的差异点：参数怎么传、结果什么格式、错误怎么报、认证怎么带——全都不统一。

## 2. 有 MCP：N+M

```
                ┌──► MCP Server: 文件系统
你的Agent ──────┤──► MCP Server: 数据库
Claude    ──┐   │──► MCP Server: 浏览器
Cursor    ──┼───┤──► MCP Server: Slack
评测平台  ──┘   └──► 你的 server（本教程 mcpd/server.py）
      ▲
      └── 所有客户端讲同一种协议（JSON-RPC over stdio/HTTP）
```

- 工具方：实现一次 server，所有 MCP 客户端都能用
- 客户端方：写一次 client，接入所有 MCP server
- 数量从 N×M 降到 N+M——这就是"工具界的 USB 接口"的具体含义

## 3. 协议分层：transport 与 protocol 是两层

MCP 的消息体是 JSON-RPC 2.0（protocol 层），怎么送达是 transport 层的事：

| 传输 | 形态 | 典型场景 |
|---|---|---|
| stdio | server 作为客户端的**子进程**，stdin/stdout 传 JSON-RPC | 本教程 `mcpd/server.py`；Claude Desktop 本地工具 |
| streamable HTTP | server 是独立 HTTP 服务，支持流式响应 | 生产部署、远程共享（见 06 篇） |
| SSE（旧） | HTTP POST + SSE 下行 | 逐步被 streamable HTTP 取代 |

**动手时先建立的直觉**：stdio 下 stdout 是协议通道——server 里一行 `print("debug")`
就会污染 JSON-RPC 帧让客户端解析失败（02 篇会再强调，`scripts/01_mcp_server.py`
的清单打印全部走 stderr 就是为此）。

## 4. resources vs tools：读与写的分界

| | tools | resources |
|---|---|---|
| 语义 | **动作**：执行查询、计算、写文件 | **数据**：可被读取的上下文内容 |
| 谁触发 | LLM 决定调用（Function Calling） | 客户端/应用决定挂载（如把一个文件作为上下文） |
| 本教程 | `search_kb` / `calc` / `save_note` | 未展开（FastMCP 一行 `@mcp.resource` 即可加） |

选择经验法则：**需要 LLM 自主决策"要不要做"的，做成 tool；只是喂背景资料的，做成 resource。**

## 5. 什么时候值得自己写 server

值得写（本教程路线）：
- 工具是**私有的**：内部 API、公司知识库、内部系统（本教程的 `search_kb` 就是模拟）
- 想给多个 Agent/同事复用：写一次，Claude Desktop / 自研 Agent / 评测平台都能挂
- 学习与排障：亲手写过一遍，接别人的 server 时秒懂日志和报错

不值得写（用现成的）：
- 通用需求（文件系统、GitHub、Postgres…）社区已有官方或高星 server，直接配
- 只在单一脚本里用一次的工具：直接本地函数，别为了协议而协议

判断口诀：**"这个工具会不会被第二个客户端用？"会 → MCP；不会 → 本地函数。**

## 6. 本教程 A 部分的地图

```
mcpd/kb.py      迷你知识库（server 与多智能体 worker 共用数据，检索实现极简）
mcpd/server.py  4 个工具 + 三契约注释（02 篇逐行讲）
mcpd/client.py  子进程生命周期 + list_tools→FC schema + call_tool 回填（03 篇讲）
```

## 思考题

1. 一个内部报表系统想被公司里 5 个不同的 Agent 应用调用。不引 MCP 的话需要多少套集成代码？引 MCP 后呢？
2. "把公司年报 PDF 的全文挂进当前对话上下文"更适合做成 tool 还是 resource？为什么？
3. 为什么 stdio server 里的 `print("debug")` 会造成客户端握手失败？

### 参考答案

1. 不引 MCP：5 套集成（每应用一套，含参数/结果/错误/认证的适配）。引 MCP：写 1 个 server + 每个应用写 1 次通用 client（且多数 MCP 客户端已内置）——集成代码从 5 降到约 1+5 次配置，且工具接口只维护一份。
2. resource。它是"可读取的数据"而非"需要 LLM 决策执行的动作"；用 resource 挂载后应用可控制何时注入上下文，不占用工具调用轮次。（注：若希望模型能"按需检索年报片段"，则把检索做成 tool、全文做成 resource，两者配合。）
3. stdio 传输中 stdout 专用于 JSON-RPC 帧；父进程按协议解析 stdout 字节流，混入的普通文本会被当成非法 JSON-RPC，导致 initialize 响应解析失败、握手中断。调试输出必须走 stderr（子进程的 stderr 默认被父进程透传到终端，不影响协议）。

---

*上一课：003 MCP 协议（概念） | 本篇：01 为什么需要 MCP | 下一课：[02 写一个 MCP server](02-write-mcp-server.md)*
