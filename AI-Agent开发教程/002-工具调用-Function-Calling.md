# 002 工具调用（Function Calling）

## 本课要点

Agent 能力的核心来源。

- 用 JSON Schema 定义工具：名称、描述、参数
- LLM 返回 `tool_calls`（结构化的调用意图）
- **你的代码**负责真正执行（查数据库、跑命令、调 API）
- 结果作为 `tool` 角色消息回填给 LLM

## 工具定义示例

```python
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
```

## 关键认知

**LLM 只决定"调什么"，执行环境在你手里 —— 这就是安全边界所在。**

## 常见坑

- 工具描述写得差 → LLM 选错工具
- 参数没有校验 → 注入风险
- 工具结果太长 → 撑爆上下文窗口（应截断/摘要）

### 代码案例：参数校验 + 结果截断的安全包装层

```python
from pydantic import BaseModel, ValidationError

# 1. 用 Pydantic 定义每个工具的入参模型
class GetWeatherArgs(BaseModel):
    city: str

# 2. 白名单分发 + 校验 + 截断，统一入口
MAX_RESULT_CHARS = 4000

def safe_invoke(name: str, raw_args: str) -> str:
    if name not in TOOL_REGISTRY:
        return f"ERROR: 未知工具 {name}"

    try:
        args = TOOL_REGISTRY[name].__args_model__.model_validate_json(raw_args)
    except ValidationError as e:
        return f"ERROR: 参数不合法，请修正后重试：{e}"   # 回填给 LLM 自己纠正

    try:
        result = TOOL_REGISTRY[name](**args.model_dump())
    except Exception as e:
        return f"ERROR: 执行失败：{e}"

    result = str(result)
    if len(result) > MAX_RESULT_CHARS:      # 防撑爆上下文（007 课）
        result = result[:MAX_RESULT_CHARS] + f"...[截断，共 {len(result)} 字符]"
    return result
```

要点：
- **校验失败不抛异常**，而是把错误作为工具结果回填——LLM 会自己修正参数重试（004 课反思机制）
- LLM 输出的 `raw_args` 是不可信输入，必须过 schema 校验再执行

## 思考题

1. 如何让 LLM 在 20 个工具中准确选对？（提示：描述分组、渐进披露）

### 参考答案

核心思路：**降低选择难度，而不是堆更多工具**。

1. **写好描述**：用"什么时候用 / 什么时候不用"的对比写法
   - ❌ `get_weather`: "查询天气"
   - ✅ `get_weather`: "查询指定城市的当前天气。仅当用户问实时天气时使用；查历史气候请用 climate_stats"
2. **命名规范**：动词_名词，让工具名本身携带语义（`search_orders` 而非 `tool1`）
3. **描述分组**：20 个工具按领域分组（文件类/搜索类/订单类），组名写进系统提示
4. **渐进披露（两层加载）**：
   - 第一层：只给一个 `list_tools(domain)` 元工具 + 简短目录
   - 第二层：LLM 先查目录，再获取选中工具的完整 schema
   - 类似人类"先看菜单，再看菜详情"
5. **few-shot 示例**：在提示词里给 2-3 个"问题 → 选哪个工具"的范例

判断标准：如果 LLM 经常选错或犹豫，优先怀疑描述重叠，而不是换更强的模型。

---

*上一课：001 核心架构 | 下一课：003 MCP*
