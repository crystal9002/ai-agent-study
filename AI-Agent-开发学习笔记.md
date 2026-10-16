# AI Agent 开发学习笔记

> 从零开始学习 AI Agent 开发的关键知识点，按编号顺序学习。

---

## 001 核心架构：Agent 循环

Agent 的本质是一个循环（ReAct 模式）：

```
感知 → 规划 → 行动 → 观察 → 反思 → (回到感知)
```

- **LLM 是"大脑"**：负责推理、决策、选择工具
- **循环终止条件**：LLM 不再调用工具时，输出的文本就是最终答案
- 理解了这个循环，就理解了所有 Agent 框架的底层逻辑

---

## 002 工具调用（Function Calling）

Agent 能力的核心来源。

- 用 JSON Schema 定义工具：名称、描述、参数
- LLM 返回 `tool_calls`（结构化的调用意图）
- **你的代码**负责真正执行（查数据库、跑命令、调 API）
- 结果作为 `tool` 角色消息回填给 LLM

关键认知：**LLM 只决定"调什么"，执行环境在你手里 —— 这就是安全边界所在。**

---

## 003 MCP（Model Context Protocol）

工具/上下文接入的事实标准协议。

- 统一了 LLM 与外部工具、数据源的连接方式
- 一次实现，处处可用（不同 Agent、不同模型都能复用）
- 类比：工具界的 USB 接口

---

## 004 规划与任务分解

复杂任务需要拆解：

- **任务拆解**：大目标 → 子目标 → 具体步骤（Todo 管理）
- **反思与自我纠错**：检查中间结果、失败重试、回滚
- **反思实现方式**：把错误作为 tool 结果回填，LLM 会自己换方案

---

## 005 记忆机制

| 类型 | 方案 | 说明 |
|------|------|------|
| 短期记忆 | 上下文窗口管理 | 截断、摘要压缩历史对话 |
| 长期记忆 | 向量数据库（RAG） | 语义检索相关知识 |
| 结构化记忆 | 记忆文件 | Agent 自己读写笔记（如 CLAUDE.md） |

关键认知：**`messages` 数组就是 Agent 的工作记忆**，每轮必须完整回填，否则 LLM "失忆"。

---

## 006 多智能体协作

- **角色分工**：Planner（规划）/ Executor（执行）/ Reviewer（审查）
- **子 Agent 派发**：主 Agent 把子任务交给专门的子 Agent
- **通信设计**：共享状态、消息协议、结果汇总

---

## 007 上下文工程

比提示词工程更重要：控制"喂什么、何时喂、喂多少"。

- 上下文窗口是稀缺资源
- 只保留当前任务相关的信息
- 关键信息放首尾，中间容易被忽略

---

## 008 可靠性工程

生产环境必须解决的问题：

- **幂等性**：同样的请求重复执行不产生副作用
- **错误处理**：超时、重试、降级
- **输出校验**：JSON Schema 校验 LLM 输出
- **循环上限**：最大轮次限制，防止无限循环烧钱
- **成本控制**：模型分级路由、缓存、流式输出

---

## 009 评估与观测

- **轨迹日志（Tracing）**：记录每一步的输入/输出/耗时/成本
- **评估方式**：
  - 端到端：任务成功率
  - 单步：工具选择准确率、输出质量评测
- 没有观测 = 没法迭代优化

---

## 010 手写 ReAct Agent（最小实现）

不用框架，纯 Python 实现一个 Agent 循环：

```python
import json
from openai import OpenAI

client = OpenAI()
tools = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "查询城市天气",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    }
}]

def get_weather(city: str) -> str:
    return f"{city}: 晴, 25°C"  # 模拟外部调用

TOOL_REGISTRY = {"get_weather": get_weather}

def run_agent(user_input: str, max_turns: int = 10):
    messages = [{"role": "user", "content": user_input}]

    for _ in range(max_turns):          # 循环上限，防烧钱
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=tools,
        )
        msg = resp.choices[0].message
        messages.append(msg)            # 回填 assistant 消息

        if not msg.tool_calls:
            return msg.content          # 不再调工具 = 最终答案

        for tc in msg.tool_calls:       # 执行每个工具调用
            fn = TOOL_REGISTRY[tc.function.name]
            try:
                result = fn(**json.loads(tc.function.arguments))
            except Exception as e:
                result = f"ERROR: {e}"  # 错误回填，LLM 会自己纠错
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": str(result),
            })

    return "达到最大轮次，终止"
```

### 关键理解点

1. **循环终止**：LLM 不返回 `tool_calls` 时输出最终答案
2. **消息回填是状态**：`messages` 就是工作记忆，必须完整
3. **执行环境是你的代码**：安全边界所在
4. **反思只需多一轮**：错误作为 tool 结果回填，LLM 自己重试

---

## 011 推荐学习路径

1. ✅ 读完本笔记（概念）
2. 手写一个 ReAct 循环（010 节代码，不用框架）
3. 实现一个带 2-3 个工具的 Agent
4. 加入记忆 + 任务分解
5. 学习框架：LangGraph、Claude Agent SDK、OpenAI Agents SDK

---

## 012 进阶练习清单

- [ ] 加一个 `run_shell` 工具（体会权限控制的必要性）
- [ ] 加最大循环次数上限（防止无限循环烧钱）
- [ ] 工具改成从配置文件/注册表动态加载
- [ ] 加 tracing：打印每轮 messages 快照和 token 消耗
- [ ] 实现对话历史摘要（短期记忆）
- [ ] 接入向量数据库做 RAG（长期记忆）
