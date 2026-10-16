# 任务规划型 Agent 实战教程

**从零手写一个 Plan-and-Execute Agent**（规划 → 逐步 ReAct 执行 → 汇总），
原生实现讲透原理，再给出 LangGraph 生产版对照——与同目录下的
[RAG 教程](../rag-knowledge-base-tutorial/README.md)同一风格。

场景：**差旅规划**——给它一个目标"下周二到周四去上海出差"，它会自己
拆解计划、查航班/酒店/天气、看日历排日程、算费用，最后产出一份完整行程方案。

## 学习路径

| 阶段 | 文档 | 对应代码 |
|------|------|----------|
| 1. Agent 原理（ReAct / Plan-and-Execute） | [docs/01-agent-principle.md](docs/01-agent-principle.md) | — |
| 2. 工具与 Function Calling | [docs/02-tools.md](docs/02-tools.md) | `agent/tools.py` |
| 3. 规划与执行循环 | [docs/03-planning.md](docs/03-planning.md) | `agent/planner.py` `agent/executor.py` `agent/task_agent.py` |
| 4. LangGraph 框架写法 | [docs/04-langgraph.md](docs/04-langgraph.md) | `scripts/02_langgraph.py` |
| 5. 生产化落地 | [docs/05-production.md](docs/05-production.md) | — |

## 快速开始

### 1. 安装

```bash
cd agent-tutorial
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 填 OPENAI_BASE_URL / OPENAI_API_KEY / LLM_MODEL
```

### 2. 运行原生版

```bash
python scripts/01_task_agent.py
# 或自定义目标：
python scripts/01_task_agent.py "下周三去深圳见客户，往返两天，安排一下"
```

输出过程：📋 任务计划 → ▶ 逐步执行（带 🔧 工具调用明细）→ 📄 最终方案，并保存到 `output/itinerary.md`。

### 3. 运行 LangGraph 版（对照）

```bash
pip install -r requirements-framework.txt
python scripts/02_langgraph.py
```

## 项目结构

```
agent-tutorial/
├── README.md
├── requirements.txt / requirements-framework.txt
├── .env.example
├── agent/                       # 原生实现（逐文件阅读）
│   ├── tools.py                 # 工具注册表 + 7 个差旅场景工具（含安全求值/路径防御）
│   ├── llm.py                   # OpenAI 兼容 Function Calling 封装
│   ├── planner.py               # 目标 → 结构化 Plan（JSON 解析）
│   ├── executor.py              # 单步 ReAct 循环（tool_calls 回填 + max_iters）
│   └── task_agent.py            # 编排：规划 → 逐步执行 → 汇总
├── scripts/
│   ├── 01_task_agent.py         # 原生版入口
│   ├── 02_langgraph.py          # LangGraph 版（@tool + StateGraph + create_react_agent）
│   └── output/                  # 生成的行程方案
├── docs/                        # 5 篇教程（按学习路径阅读）
```

## 核心链路

```
目标
 │ ① 规划：LLM 输出 {"steps":[{id, goal, tools}]}   ← planner.py
 ▼
┌─ 逐步执行（for step in plan）──────────────────────┐
│  ② 每步一个 ReAct 循环：                           │
│     思考 → tool_calls → 执行 → tool 结果回填 → …   │  ← executor.py
│     直到模型输出结论 / 超过 max_iters               │
│  ③ 步骤结论累积为 history，传给下一步               │
└───────────────────────────────────────────────────┘
 │ ④ 汇总：目标 + 计划 + 各步结果 → Markdown 方案    ← task_agent.py
 ▼
最终行程方案（output/itinerary.md）
```

## 两种范式一句话区分

- **ReAct**：解决"这一步怎么干"——模型自主决定调什么工具、调几次（`executor.py`）
- **Plan-and-Execute**：解决"这个任务怎么排"——先出计划再逐步执行，计划可见可控（`task_agent.py`）

生产建议与人工确认、状态持久化、工具网关等见 [docs/05-production.md](docs/05-production.md)。
