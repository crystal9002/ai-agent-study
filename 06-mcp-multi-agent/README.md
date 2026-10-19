# MCP 协议实战 + 多智能体协作教程

**从零手写一个 MCP server 并接进 Agent，再手写一套 supervisor/worker 多智能体**，
最后给出 LangGraph 框架对照——与同目录下的
[02-Agent 教程](../02-agent-tutorial/README.md)、[01-RAG 教程](../01-rag-knowledge-base-tutorial/README.md)同一风格。

概念课见 [AI-Agent开发教程 003 MCP协议](../AI-Agent开发教程/003-MCP协议.md) 与
[006 多智能体协作](../AI-Agent开发教程/006-多智能体协作.md)——本教程**不重复讲概念，全部是动手**：

- **A 部分**：手写 MCP server（FastMCP）→ stdio 客户端 → 把 MCP 工具挂进 Agent 的 Function Calling 循环
- **B 部分**：手写消息总线 + supervisor 路由 + 3 个 worker（检索/计算/写作）→ SSE 可视化 → LangGraph 对照

## 学习路径

| 阶段 | 文档 | 对应代码 |
|------|------|----------|
| 1. 为什么需要 MCP（N×M 痛点） | [docs/01-why-mcp.md](docs/01-why-mcp.md) | — |
| 2. 写一个 MCP server | [docs/02-write-mcp-server.md](docs/02-write-mcp-server.md) | `mcpd/server.py` `mcpd/kb.py` |
| 3. 客户端接入与 Agent 桥接 | [docs/03-client-bridge.md](docs/03-client-bridge.md) | `mcpd/client.py` `scripts/02_mcp_agent.py` |
| 4. 手写多智能体（supervisor/worker） | [docs/04-multi-agent.md](docs/04-multi-agent.md) | `multi/` `scripts/03_multi_agent.py` |
| 5. LangGraph 框架写法 | [docs/05-langgraph.md](docs/05-langgraph.md) | `scripts/05_langgraph.py` |
| 6. 生产化落地 | [docs/06-production.md](docs/06-production.md) | — |

## 快速开始

### 1. 安装（系统 python 过旧时用 uv 指定 3.12）

```bash
cd 06-mcp-multi-agent
uv venv --python /usr/local/bin/python3.12 .venv
uv pip install -p .venv/bin/python -r requirements.txt
cp .env.example .env   # 填 OPENAI_BASE_URL / OPENAI_API_KEY / LLM_MODEL
```

### 2. 验证 MCP server

```bash
.venv/bin/python scripts/01_mcp_server.py
# stderr 打印 search_kb / calc / get_time / save_note 四个工具后进入 stdio 服务（Ctrl+C 退出）
```

### 3. 跑 MCP Agent（工具经 stdio 子进程接入）

```bash
.venv/bin/python scripts/02_mcp_agent.py "50人团队版一年多少钱？"
# 日志可见 🔧 MCP 调用 → search_kb / calc，最终回答带数据来源
```

### 4. 跑多智能体（supervisor 路由 + 3 worker 分工）

```bash
.venv/bin/python scripts/03_multi_agent.py
# 事件轨迹：🧠 路由 → 📤 分派 → 🔧 worker 工具调用 → ✅ 交回 → 🏁 汇总
# 产出 output/summary.md
```

### 5. Web 界面（SSE 实时泳道）

```bash
.venv/bin/python scripts/04_web.py        # http://127.0.0.1:8005
# supervisor 与 3 个 worker 分列泳道，路由/分派/工具调用/交回实时滚动
```

### 6. LangGraph 对照版

```bash
uv pip install -p .venv/bin/python -r requirements-framework.txt
.venv/bin/python scripts/05_langgraph.py
# 同一目标、同一 worker，看 StateGraph + 条件边怎么替代手写 for 循环
```

## 项目结构

```
06-mcp-multi-agent/
├── README.md
├── requirements.txt / requirements-framework.txt
├── .env.example
├── llm.py                        # OpenAI 兼容 LLM 封装（chat / chat_json）
├── mcpd/                         # A. MCP 部分
│   ├── server.py                 # FastMCP server（stdio）：search_kb/calc/get_time/save_note
│   ├── client.py                 # stdio 客户端 + MCP→OpenAI FC schema 适配 + 同步桥
│   └── kb.py                     # 内嵌迷你知识库（纯关键词检索，server 与 worker 共用）
├── multi/                        # B. 多智能体部分
│   ├── bus.py                    # 消息总线：Message + EventBus（历史/订阅广播）
│   ├── agents.py                 # WorkerAgent：检索/计算/写作（各自 system + 工具子集）
│   ├── supervisor.py             # Supervisor：LLM 路由 JSON、分发、验收、失败重派一次
│   └── runner.py                 # 编排入口：run(goal, on_event) → 事件流
├── scripts/
│   ├── 01_mcp_server.py          # 独立启动 server，打印工具清单（走 stderr）
│   ├── 02_mcp_agent.py           # Agent 循环 + MCP 工具（stdio 子进程）
│   ├── 03_multi_agent.py         # supervisor/worker CLI，全事件轨迹
│   ├── 04_web.py                 # FastAPI + SSE（8005）
│   └── 05_langgraph.py           # LangGraph 对照（StateGraph + 条件边）
├── web/index.html                # 泳道式实时 UI（原生 JS，无构建）
└── docs/                         # 6 篇教程（按学习路径阅读）
```

## 核心链路 ①：MCP 接入（scripts/02）

```
问题 "50人团队版一年多少钱？"
 │
 ▼
┌─ Agent 主进程（scripts/02_mcp_agent.py）────────────────────────┐
│  ① SyncMCPBridge.connect()                                     │
│     └─ 子进程拉起 mcpd/server.py（stdio），JSON-RPC 握手         │  ← mcpd/client.py
│  ② list_tools() → mcp_tools_to_openai() → tools=[search_kb,…]  │
│  ③ LLM.chat(messages, tools)  →  返回 tool_calls               │  ← llm.py
│  ④ call_tool(name, args)  ──stdio(JSON-RPC)──►  server 执行     │
│     ◄────────────── 结果 JSON 文本回填 messages(role=tool) ───── │
│  ⑤ 循环 ③④ 直到模型不再调工具（max_iters 兜底）                 │
└─────────────────────────────────────────────────────────────────┘
 │
 ▼
最终回答（数字均标注来自 search_kb / calc）
```

## 核心链路 ②：supervisor 路由（scripts/03/04）

```
目标："查团队版定价 → 算50人年费 → 写成 summary.md"
 │
 ▼
┌─ Supervisor（multi/supervisor.py）──────────────────────────────┐
│  round 1: LLM 输出 {"action":"dispatch","worker":"researcher"} │
│  round 2: 收到定价事实 → {"worker":"calculator","task":…}      │
│  round 3: 收到计算结果 → {"worker":"writer","task":…}          │
│  round 4: 材料齐全 → {"action":"answer","content":…}           │
│  （worker 失败 → 带原因重派一次，再失败放弃）                    │
└───────────┬──────────────┬──────────────┬──────────────────────┘
            ▼              ▼              ▼
     🔍 researcher    🧮 calculator   ✍️ writer
     工具: search_kb   工具: calc      工具: save
     独立上下文        独立上下文       独立上下文
            │              │              │
            └────── EventBus（消息历史 + on_event 广播）─────────┘
                          │
            CLI 打印轨迹 / SSE 推给 web/index.html 泳道图
```

## 两种接入方式一句话区分

- **MCP**：解决"工具从哪来"——server 一次实现，任何支持 MCP 的客户端动态发现、即插即用
- **多智能体**：解决"活谁来干"——上下文隔离、权限分立，supervisor 统一路由与验收

生产化考量（streamable HTTP 部署、工具审批、tracing、避免过度拆分）见
[docs/06-production.md](docs/06-production.md)。
