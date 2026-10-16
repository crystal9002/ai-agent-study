# 02 · 工具与 Function Calling

代码：`agent/tools.py`、`agent/llm.py`

## Function Calling 的本质

模型**不执行**工具——它只是输出一个结构化意图：

```json
{"tool_calls": [{"id": "call_1", "type": "function",
  "function": {"name": "search_flights", "arguments": "{\"origin\":\"北京\",...}"}}]}
```

执行权永远在你的程序：校验 → 执行 → 把结果以 `role: "tool"` 消息回填 → 模型看到结果继续思考。**这是安全边界：模型只能"建议"，一切副作用由你把关。**

一次完整交互（`executor.run_step` 中的循环体）：

```
assistant 消息(含 tool_calls) → 你执行工具 → tool 消息(结果) → assistant …
```

## 本项目的最小工具注册表

`ToolRegistry` 解决三件事：

1. **签名推导 Schema**：`Tool.__init__` 用 `inspect` 读取参数名、类型注解、docstring，
   自动生成 function calling 要求的 JSON Schema（`_json_type` 处理 `list[str]` 等）。
   → 新增工具 = 写一个带类型注解的普通函数 + `registry.register(fn)`，零胶水代码。
2. **统一调用与错误兜底**：`invoke()` 捕获 JSON 解析错误、参数不匹配、运行时异常，
   一律转成 `{"error": "..."}` 回给模型。**工具绝不抛异常**——异常会打断循环，而模型看到错误后往往能换参数自救。
3. **规格输出**：`specs()` 生成 OpenAI `tools` 参数，直接传给 `llm.chat(tools=...)`。

## 场景工具集（7 个）

| 工具 | 作用 | 教学点 |
|------|------|--------|
| `search_flights` | 查航班（按航线+日期生成确定性数据） | 多次调用组合 |
| `search_hotels` | 查酒店（预算过滤） | 参数约束 |
| `get_weather` | 查天气 | 无副作用只读 |
| `get_calendar` / `add_calendar_event` | 查/写日历 | **有副作用的写操作** |
| `calc` | 四则运算 | **安全求值**：用 AST 白名单求值，绝不 `eval()` |
| `save_itinerary` | 保存文件 | **路径穿越防御**（`Path.name` 剥离目录） |

模拟数据用输入的 md5 哈希生成 → 同一提问结果可复现，方便演示与测试。

## 工具设计的工程原则（生产必读）

1. **描述即 API 文档**：模型完全靠 `description` 决定何时用、怎么传参——写清语义边界、参数格式、返回结构、与相近工具的区别。
2. **返回信息要足量**：模型的"观察"只有你回填的内容。返回太少 → 模型瞎猜；太长 → 挤占上下文。结构化 + 关键字段优先。
3. **读写分离、权限最小**：只读工具可自由调用；写操作（下单、删数据）加**人工确认**或白名单（见 [05](05-production.md)）。
4. **幂等与超时**：网络类工具可能被重试，需幂等；设置超时并把超时转成可读错误。
5. **限制循环次数与工具调用数量**：`max_iters` 是成本与失控的最后防线。

## 下一步

[03 · 规划与执行](03-planning.md)
