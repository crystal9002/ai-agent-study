# 010 手写 ReAct Agent（最小实现）

## 本课要点

不用框架，纯 Python 实现一个 Agent 循环。**这是本教程最重要的一课。**

## 完整代码

```python
import json
from openai import OpenAI

client = OpenAI()

# 1. 定义工具（JSON Schema）
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

# 2. 实现工具（执行环境在你手里）
def get_weather(city: str) -> str:
    return f"{city}: 晴, 25°C"  # 模拟外部调用

TOOL_REGISTRY = {"get_weather": get_weather}

# 3. Agent 循环
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

## 关键理解点

1. **循环终止**：LLM 不返回 `tool_calls` 时输出最终答案
2. **消息回填是状态**：`messages` 就是工作记忆，必须完整
3. **执行环境是你的代码**：安全边界所在
4. **反思只需多一轮**：错误作为 tool 结果回填，LLM 自己重试

## 运行

```python
print(run_agent("北京今天天气怎么样？"))
```

## 思考题

1. 如果去掉 `messages.append(msg)` 会发生什么？
2. 如何支持一个用户请求触发多个并行工具调用？（提示：代码已经支持，思考为什么）

### 参考答案

**1. 去掉 `messages.append(msg)` → 立即报 API 错误**

OpenAI 协议要求：每条 `tool` 消息之前必须有一条**包含对应 `tool_calls` 的 assistant 消息**（通过 `tool_call_id` 配对）。去掉回填后，下一轮发送的 messages 里只有 `role: "tool"` 而找不到配对的 assistant 消息，API 会直接返回 400 错误（类似 "assistant message with 'tool_calls' must be followed by tool messages" / 反向缺失）。

更深层理解——即使协议不报错，也会致命：
- LLM 看不到自己上一轮**决定调什么**（意图丢失）
- 看不到**调用结果**（观察丢失）
- Agent 退化成每轮都从零开始，循环彻底失效

结论：`messages` 就是 Agent 的状态机，每条消息都是状态的一部分。

**2. 并行工具调用：代码天然支持，因为设计上是"逐个回填"**

原因在于两点：
- **LLM 侧**：模型可以在一条 assistant 消息里返回多个 `tool_calls`（如同时查北京、上海天气）
- **代码侧**：`for tc in msg.tool_calls` 是循环体，每个工具执行完都各自 append 一条 `tool` 消息，`tool_call_id` 一一对应

所以并行调用已被正确处理。

**但要注意两个细节：**
1. **顺序执行 vs 真并行**：上面的 for 循环是串行 await，工具多时慢——可用 `asyncio.gather` 改成真并发
2. **必须全部回填**：协议要求该轮**每一个** `tool_call` 都要有对应的 tool 消息，即使某个工具失败了，也要回填错误信息，否则 API 报错

---

*上一课：009 评估观测 | 下一课：011 推荐学习路径*
