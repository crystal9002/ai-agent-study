# 知识库助手 Agent 实战教程（RAG × Agent 组合）

**把 RAG 检索包成 Agent 的一个工具**：模型自己决定何时检索、检索几次、要不要算账、
何时落盘结论——原生实现讲透原理，再给 LangGraph 生产版对照。
与 [RAG 教程](../01-rag-knowledge-base-tutorial/README.md)、
[Agent 教程](../02-agent-tutorial/README.md)同一风格。

场景：**企业内部"星云笔记"知识库助手**——用户问产品/价格/接口类问题时，Agent 先调
`search_kb` 检索，基于证据回答并带 `[n]` 引用；也能做组合任务（"查出团队版价格，
用 calc 算 50 人年费，把结论写进 note 文件"）。

## 学习路径

| 阶段 | 文档 | 对应代码 |
|------|------|----------|
| 1. 为什么组合：RAG 与 Agent 的分工 | [docs/01-why-composition.md](docs/01-why-composition.md) | `data/` `kba/kb.py` |
| 2. 检索即工具：schema 与 prompt 合同 | [docs/02-search-as-tool.md](docs/02-search-as-tool.md) | `kba/tools.py` `kba/agent.py` |
| 3. 原生 ReAct 循环逐行讲解 | [docs/03-agent-loop.md](docs/03-agent-loop.md) | `kba/agent.py` `kba/llm.py` |
| 4. LangGraph 框架对照 | [docs/04-langgraph.md](docs/04-langgraph.md) | `scripts/04_langgraph.py` |
| 5. 生产化落地 | [docs/05-production.md](docs/05-production.md) | — |

## 快速开始

> 本机注意：系统 python3 是 3.7 不可用，必须用 python3.12 建虚拟环境；
> Intel Mac 上 torch 最高 2.2.2，依赖已钉版本（见 `requirements.txt`）。

### 1. 安装

```bash
cd 03-knowledge-base-agent
uv venv --python /usr/local/bin/python3.12 .venv
uv pip install -q -p .venv/bin/python -r requirements.txt
cp .env.example .env   # 填 OPENAI_BASE_URL / OPENAI_API_KEY / LLM_MODEL
```

### 2. 建知识库索引

```bash
.venv/bin/python scripts/01_build_kb.py
# 扫描 data/ 下 3 份 md → 分块 → 本地 bge 向量化 → FAISS + BM25 混合索引
```

### 3. CLI 跑 Agent（工具轨迹 + 带引用回答）

```bash
.venv/bin/python scripts/02_kb_agent.py "团队版多少钱？50个人一年多少钱？"
```

输出：`🔧 search_kb(...)` 命中明细 → `🔧 calc(...)` 算账 → 最终回答带 `[n]` 引用与来源清单。

### 4. Web 界面（SSE 实时进度，端口 8002）

```bash
.venv/bin/python scripts/03_web.py        # 打开 http://127.0.0.1:8002
```

或直接看 SSE 事件流（中文参数必须 `--data-urlencode`）：

```bash
curl -s -G http://127.0.0.1:8002/api/query --data-urlencode "q=团队版多少钱？"
# event: start → tool_call → tool_result → … → final → done
```

### 5. LangGraph 框架版（对照）

```bash
uv pip install -q -p .venv/bin/python -r requirements-framework.txt
.venv/bin/python scripts/04_langgraph.py "团队版多少钱？50个人一年多少钱？"
```

## 项目结构

```
03-knowledge-base-agent/
├── README.md
├── requirements.txt / requirements-framework.txt   # framework: langgraph + langchain-openai
├── .env.example / .env                            # LLM 配置（.env 已被根 .gitignore 忽略）
├── .gitignore                                     # 忽略 index/ output/ .venv 等生成物
├── data/                      # 自带 3 份中文示例：产品手册 / 价格FAQ / API 文档（星云笔记）
├── kba/                       # 原生实现（逐文件阅读）
│   ├── kb.py                  # 精简 RAG：分块 + 本地 bge 向量化 + FAISS + BM25/RRF 混合召回
│   ├── tools.py               # 工具注册表（签名自动推 Schema）+ search_kb/calc/write_note/list_notes
│   ├── llm.py                 # OpenAI 兼容 Function Calling 封装
│   └── agent.py               # ReAct 循环：tool_calls 回填 + max_iters 兜底 + 引用 prompt 合同
├── scripts/
│   ├── 01_build_kb.py         # 建索引（离线）
│   ├── 02_kb_agent.py         # CLI：工具轨迹 + 带引用回答
│   ├── 03_web.py              # FastAPI + SSE（端口 8002，事件 start/tool_call/tool_result/final）
│   ├── 04_langgraph.py        # 框架对照：create_react_agent + @tool
│   └── output/                # Agent 写入的笔记（write_note 产物）
├── web/                       # 单页前端（原生 HTML/JS，无构建步骤）
├── index/                     # 生成的向量索引（不入库）
└── docs/                      # 5 篇教程（按学习路径阅读）
```

## 一次问答的完整链路

```
用户问题："团队版多少钱？50个人一年多少钱？"
 │
 │ ① 组装 messages：system(引用合同) + user(问题)          ← agent.py SYSTEM
 ▼
┌─ ReAct 循环（for _ in range(max_iters=6)）────────────────────────┐
│  ② LLM 返回 tool_calls                                          │
│     {"name":"search_kb","args":{"query":"团队版价格","k":5}}      │  ← llm.py chat()
│  ③ 宿主执行工具 → 结果以 role:"tool" 回填（错误转 {"error":…}）   │  ← tools.py invoke()
│        search_kb → kba/kb.py：向量+BM25 → RRF → top-k，带编号 n   │
│  ④ LLM 看到证据 → 再调 calc("25*12*0.8*50") → 12000              │
│  ⑤ 直到模型不再返回 tool_calls → 输出结论（否则超轮数兜底）        │
└──────────────────────────────────────────────────────────────────┘
 │
 ▼
回答："年付 240 元/人/年 × 50 = 12,000 元/年 [2] …… 来源：[2] pricing_faq"
      （Web 版把 start/tool_call/tool_result/final 逐事件 SSE 推到浏览器）
```

## 与 01 / 02 教程的关系

一句话：**01 教程的检索链路（`rag/`）在本教程被压缩成 `kba/kb.py` 并包成工具，02 教程的
循环骨架（`executor.py`）在本教程简化成单循环 ReAct（`kba/agent.py`）**——两者相乘就是
"会查知识库的 Agent"。
