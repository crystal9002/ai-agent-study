# 02 写一个 MCP Server（FastMCP 逐行）

> 上一课：[01 为什么需要 MCP](01-why-mcp.md) | 下一课：[03 客户端接入与桥接](03-client-bridge.md)
> 对应代码：`mcpd/server.py` `mcpd/kb.py`；验证入口：`scripts/01_mcp_server.py`

## 0. 对照 02 教程的本地工具注册表

02 教程 `agent/tools.py` 里我们手写过 `ToolRegistry`：装饰器注册 → 签名推导 JSON Schema
→ `registry.specs()` 喂给 LLM → `registry.invoke()` 统一调用。**FastMCP 做的就是同一件事，
只是把"注册表"升级成了"网络服务"**：

| | 02 教程 ToolRegistry | FastMCP server |
|---|---|---|
| 注册 | `@registry.register` | `@mcp.tool()` |
| Schema 推导 | 手写 `_json_type` | SDK 自动（类型注解 + docstring） |
| 调用方 | 同进程函数调用 | 客户端经 JSON-RPC `tools/call` |
| 发现方式 | 代码里 import | 远程 `tools/list` 动态发现 |
| 错误约定 | 返回 `{"error": ...}` | 同样约定（抛异常会变 protocol error） |

结论：**工具函数本体几乎不用改，改的是"暴露方式"**。

## 1. 最小骨架

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("study-demo", instructions="演示用知识库服务：…")

@mcp.tool()
def calc(expression: str) -> dict:
    """计算数学表达式（+ - * / ** 与括号）。"""
    return {"expression": expression, "value": _safe_eval(expression)}

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

`@mcp.tool()` 自动完成：
- 从签名推导 `inputSchema`（`expression: str` → `{"type":"object","properties":{...},"required":["expression"]}`）
- docstring → 工具 description（**这段文字直接进 LLM 提示词**，写"计算数学表达式"而不是"工具A"）
- 注册进 server 内部注册表，等待 `tools/list` / `tools/call`

## 2. 本 server 的 4 个工具与三契约

`mcpd/server.py` 头部注释里的"三契约"在每个工具上的体现：

| 工具 | ① 清单契约（name/description） | ② 参数契约（inputSchema） | ③ 结果契约 |
|---|---|---|---|
| `search_kb` | "检索产品知识库（定价/功能/FAQ）" | `query: str`, `top_k: int=2` | `{"query","hits":[…],"total"}` 或 `{"error"}` |
| `calc` | "计算数学表达式" | `expression: str` | `{"expression","value"}` 或 `{"error"}` |
| `get_time` | "获取服务器当前时间" | 无参 | `{"time","weekday"}` |
| `save_note` | "保存 notes/ 下 .md 笔记" | `filename`, `content` | `{"saved_to","chars"}` 或 `{"error"}` |

写新工具时按这三列过一遍，就是完整的对外文档。

## 3. 错误返回：绝不炸进程

stdio server 的进程生命周期 = 客户端连接的生命周期。工具抛裸异常的后果轻则 protocol
error、重则进程退出、所有工具一起断连。所以：

```python
@mcp.tool()
def search_kb(query: str, top_k: int = 2) -> dict:
    try:
        return _kb_search(query, top_k=max(1, min(int(top_k), 5)))
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}   # 业务错误走返回值
```

两层防御：
- **参数层**：`top_k` 强制夹在 [1,5]，防 LLM 传 `top_k=100000` 拖垮内存
- **业务层**：`try/except` 兜底转 `{"error"}`；客户端（03 篇）会原样回填给 LLM，
  模型看到 error 会换参数重试或如实说明——这正是 Agent 容错链路的一环

`save_note` 的目录穿越防御与 02 教程 `save_itinerary` 同款：`Path(filename).name`
只取最后一段，拒绝 `../` 和非 `.md` 文件。

## 4. 安全求值：不用 eval

`calc` 复用 02 教程的 AST 白名单方案：`ast.parse` 后只放行
`Constant / BinOp(+ - * / **) / UnaryOp`，其余节点一律拒绝。**任何"执行用户字符串"
的工具都应走这条路**，`eval()` 一行就能让 MCP server 变成任意代码执行入口。

## 5. stdio 传输的三条纪律

1. **stdout 只留给协议**：调试打印走 `print(..., file=sys.stderr)`；
   FastMCP 内部日志已默认走 stderr，不要手动改 logging 到 stdout
2. **入口用 `mcp.run(transport="stdio")`**：它内部启动 anyio 事件循环并阻塞服务——
   所以外面**不要再套 `asyncio.run()`**（会报 "Already running"，`scripts/01` 踩过此坑）
3. **工作目录与解释器**：server 被客户端以子进程拉起时，`cwd`/解释器由客户端的
   `StdioServerParameters` 决定（03 篇），server 内部路径要用 `Path(__file__)` 锚定

## 6. 动手验证

```bash
.venv/bin/python scripts/01_mcp_server.py
# stderr：
# 📋 已注册工具（stdio server 即将启动，Ctrl+C 退出）:
#   - search_kb(query, top_k) …
#   - calc(expression) …
#   - get_time() …
#   - save_note(filename, content) …
# 然后进程阻塞等待 stdin 的 JSON-RPC（Ctrl+C 退出）
```

## 思考题

1. 把 `search_kb` 的 docstring 改成 `"查询工具"`，预期对 Agent 选工具的成功率有什么影响？为什么？
2. `save_note` 为什么既防目录穿越又限 `.md` 后缀？只做其一够不够？
3. 工具函数里 `raise ValueError("bad")` 和 `return {"error": "bad"}`，对客户端分别是什么表现？

### 参考答案

1. 成功率会明显下降。MCP 的 description 会原样进入 LLM 的 tools 列表提示词；模型靠它判断"什么时候该用这个工具"。"查询工具"没有领域信息（查什么？何时查？），模型只能靠参数名猜，容易漏用或误用。写 description 的公式：**做什么 + 何时用 + 参数示例**。
2. 不够，两者防的是不同攻击面：只防穿越不限后缀 → 攻击者可写 `notes/evil.py` 之类；只限后缀不防穿越 → `../../.ssh/authorized_keys.md` 仍可写到目录外（后缀检查在 `Path.name` 前做就失效）。必须先 `Path(filename).name` 消灭路径成分，再校验后缀。
3. 抛异常：FastMCP 捕获后转成 protocol/工具级 error，客户端 `call_tool` 返回 `isError=True` 的结果，我们的 client 封装会转为 `{"error": "..."}` 回填；进程不退出。`return {"error"}`：走正常成功响应，content 是 JSON 文本 `{"error":"bad"}`，客户端需解析内容判断（我们的封装两种都统一成了 `{"error"}` dict）。实践推荐后者——语义清晰、可携带结构化错误码。

---

*上一课：[01 为什么需要 MCP](01-why-mcp.md) | 下一课：[03 客户端接入与桥接](03-client-bridge.md)*
