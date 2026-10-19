# 06 生产化落地

> 上一课：[05 LangGraph 对照](05-langgraph.md) | 本教程完
> 呼应：[004 教程的 tracing/评估](../../AI-Agent开发教程/)、[006 课的成本警告](../../AI-Agent开发教程/006-多智能体协作.md)

本教程的代码是"教学最小完备"。真正上线前，MCP 侧和多智能体侧各有一串必答题。

## 1. MCP server 部署：从 stdio 到 streamable HTTP

stdio 的本质是"server 寄生在客户端进程树里"——适合本地个人工具，不适合共享服务：

| | stdio（本教程） | streamable HTTP（生产推荐） |
|---|---|---|
| 形态 | 子进程，随客户端生死 | 独立服务，多客户端共享 |
| 并发 | 1 连接 1 进程 | 服务端自行伸缩 |
| 认证 | 无（进程边界即信任边界） | Token/OAuth/mTLS |
| 改一行代码 | `mcp.run(transport="stdio")` | `mcp.run(transport="streamable-http")` + 配置 host/port |

FastMCP 对两种传输是同一套 `@mcp.tool()`——**工具代码零改动**，这就是 01 篇说的
"protocol 与 transport 分层"的红利。部署时配反向代理（HTTPS）、健康检查、
按实例数水平扩展即可。

## 2. 鉴权与工具审批：MCP 的两个信任问题

**问题 A：客户端怎么证明自己有权调用？**
- HTTP 传输：入口统一挂 Bearer Token / OAuth 校验；server 内部按 token 做工具级 ACL
  （如只读角色禁用 `save_note`）
- 本地 stdio：风险转移到"谁有权拉起你的 server 子进程"——靠系统权限，别把
  server 脚本放在低权限用户可写目录

**问题 B：LLM 决定的调用，要不要人审？**
按副作用分级（业界通行做法）：

| 级别 | 例子 | 策略 |
|---|---|---|
| 只读 | `search_kb` `get_time` `calc` | 直接放行 |
| 可逆写 | `save_note` `save`（写 output/） | 放行 + 审计日志 + 配额 |
| 不可逆/外部 | 发邮件、删数据、转账 | **必须人工审批节点**（LangGraph interrupt） |

本教程把 `save_note` 设计成"只能写 notes/ 普通 .md 文件"就是第一道闸：**代码层的
路径/后缀白名单是底线，审批流是兜底，两者都要有。**

## 3. 多智能体的 tracing：看清每一次调用

多 Agent 出问题时的排查成本是单 Agent 的平方——"calculator 答错了"可能是：
路由错、task 写漏了数字、worker 工具报错、验收放水……必须有全链路 trace：

- **本教程的事件协议已是雏形**：每个 `dispatch/worker_step/worker_done` 带
  worker、tool、args、result——接上 LangSmith / OpenTelemetry 就是完整 span 树
  （supervisor span → worker span → tool span，天然父子关系）
- **成本归因**（04 教程呼应）：按 `worker` 维度聚合 token 用量。经验数据：多 Agent
  系统里 supervisor 占 15~25% token，最重的 worker 常占 50%+——先看归因再谈优化
- **日志纪律**：总线 `history` 落盘（结构化 JSON），出问题可离线回放整个会话

## 4. 避免过度拆分：单优先原则

006 课的成本警告值得在生产语境下重述。多 Agent 的隐性账单：

```
token：每 worker 一套 system prompt + 任务重述；supervisor 每轮全量看 results
延迟：串行 N 个 worker ≈ N × (LLM 往返 + 工具耗时)
错误面：路由错/任务文本写漏/验收误放——每条链路都可能出错
```

**升级路径**（先 1 再 3 再 5）：

```
① 单 Agent + 好工具（02 教程形态）──解决不了？
② 单 Agent + 规划分解（Plan-and-Execute）──还不够？
③ 本文的 supervisor/worker ──还不够？
④ 并行 worker + 审批节点（LangGraph 的强项）
⑤ 层级 supervisor（每个域一个二级主管）
```

每上一级，先问"上一级的具体失败案例是什么"。没有具体案例，就停在当前级。

## 5. 生产检查清单

**MCP 侧**
- [ ] 传输：本地工具 stdio；共享服务 streamable HTTP + HTTPS
- [ ] 每个工具的 description 含"做什么/何时用/参数示例"（直接影响选对率）
- [ ] 参数白名单（长度/范围/枚举）+ 业务错误全走 `{"error"}` 返回
- [ ] 敏感工具分级 + 审批；审计日志记录调用者、参数、结果摘要
- [ ] server 超时与熔断：单工具超时不拖垮整个连接（客户端 `call_tool(timeout=…)`）

**多智能体侧**
- [ ] `max_rounds` / `max_iters` / `recursion_limit` 三层上限齐备
- [ ] supervisor 重派必附失败原因；每 worker 重派次数 ≤1
- [ ] 事件流接 tracing；按 worker 做 token/成本归因
- [ ] 结果验收有客观信号（文件存在、数字一致性）而非纯 LLM 感觉
- [ ] 全链路幂等：worker 重跑不产生重复副作用（save 覆盖写而非追加）

## 6. 延伸练习

1. 把 `mcpd/server.py` 以 streamable HTTP 起服务，客户端改用 HTTP 传输连接
2. 给 `save_note` 加审批：runner 里发"待审批"事件，SSE 前端加确认按钮后 resume
3. runner 改 asyncio，researcher 无依赖时并行派发，统计串行/并行耗时差
4. 接 LangSmith：对比手写版与 05 LangGraph 版在同一目标下的 token 消耗

## 思考题

1. 为什么"路径白名单"不能替代"审批流"，反之亦然？
2. 按 worker 做成本归因后，发现 supervisor 占了 60% token。可能的原因和优化手段？
3. 什么信号出现时，你应该把三个 worker 合回单 Agent？

### 参考答案

1. 白名单防的是**已知的恶意模式**（`../`、非 .md 后缀）——静态、可枚举；审批流防的是**合法参数下的有害操作**（用合规文件名覆盖掉重要笔记）。前者挡在代码层、零延迟；后者依赖人的语义判断、有延迟。只有白名单 → 合法路径的批量覆盖无人拦；只有审批 → 每次调用都等人，且 `../` 这类低级攻击浪费审批注意力。纵深防御要分层。
2. 常见原因：① results 里塞了 worker 的全文原文（没有压缩），每轮路由都重传；② supervisor 提示词让模型复述全部历史；③ 路由轮数过多（检索反复重试）。优化：worker 结构化摘要后只回传关键字段；`task` 里只带下游需要的数字；给 results 设长度上限；用 ④ 的失败归因先修"为什么反复重派"。
3. 出现以下信号时合并：各 worker 的 system prompt 趋同；路由几乎总是固定顺序（researcher→calculator→writer，没有分支决策）；token 归因显示拆分后总消耗 > 单 Agent 的 2 倍且质量无提升；跨 worker 的信息丢失导致结果错误（task 自包含写不全）。固定顺序的多步流程用单 Agent 的 Plan-and-Execute（02 教程）更便宜、更稳。

---

*上一课：[05 LangGraph 对照](05-langgraph.md) | 回到 [README](../README.md)*
