# 04 · 人工审批：human-in-the-loop 的正确姿势

## 本课要点

- 什么必须人批：**不可逆**（删除/覆盖）、**出网**（外发数据）、**越权**（超出任务范围）。
- 审批是流程不是弹窗：pending 记录 + 状态机（pending → approved/denied/expired）
  + 可审计 + **超时默认拒绝（default-deny）**。
- 打断点设计：审批发生在"策略判定之后、物理执行之前"，拒绝信息回填给 LLM 让它调整。

## 1. 什么操作必须人批

| 类型 | 例子 | 为什么 |
|------|------|--------|
| 不可逆 | delete_file、覆盖写、发消息 | 没有 undo 可以兜底 |
| 出网 | curl/邮件/IM 通知 | 数据出了边界就收不回来 |
| 越权 | 读沙箱外、访问生产系统 | 超出授权范围本身 |

反过来，**不该**人批的：读文件、列目录、只读 shell。
对它们弹确认只会制造审批疲劳，把真正危险的确认淹没掉（docs/01 思考题 1）。

## 2. 审批数据结构（`sec/approval.py`）

```python
@dataclass
class Approval:
    id: str            # apr-xxxxxxx
    tool: str          # 被请求的工具
    args: dict         # 完整参数（人要审的就是这个）
    level: str         # 权限级别
    reason: str        # 为什么要拦（给审批人看的一句话）
    run_id: str        # 归属哪次运行（审计串联）
    status: str        # pending → approved / denied / expired
    decided_by: str    # human / web / policy / timeout
    ...
```

- **args 必须完整呈现**：审批人批准的是"这个参数的这次调用"，
  模糊的"Agent 想删东西，同意吗？"没有意义；
- **run_id 串联**：从审计日志能回溯"这次删除属于哪次任务、之前读过什么"；
- 持久化为 JSONL 事件（`audit/approvals.jsonl`），重放可恢复状态。

## 3. 两种批准通道，一个状态机

```
                    ApprovalGate.ask()
                          │
          mode=deny ──────┴────── mode=ask
              │                      │
         直接 DENIED           生成 pending 记录
         （非交互默认）              │
                        ┌───────────┴───────────┐
                        │ tty?                  │ 非 tty（Web/队列）
                   命令行 y/N              轮询等待 ≤ wait_seconds
                        │                       │
                        └───────────┬───────────┘
                                    │
                  approved → allow（执行并审计）
                  denied   → DENIED 回填 LLM
                  expired  → DENIED（超时 = 拒绝）
```

关键设计：

- **default-deny**：`APPROVAL_MODE=deny`（本教程默认）非交互环境一律拒绝；
  `ask` 模式下**超时也拒绝**（`expired`）。没人在，就不动手；
- **拒绝信息回填**：`DENIED: …approval_id=xxx` 作为 tool 结果进上下文，
  LLM 会如实转达并调整方案（见 02 脚本实测输出）；
- **幂等**：对已有结论的记录重复 decide 返回现有状态，Web 双击不会出错。

## 4. UX：审批卡片上应该有什么

参照 `web/index.html` 的待审批卡片，最小要素：

1. 工具名 + 权限级别（⚠ delete_file · destructive）；
2. 完整参数（等宽字体展示 `{"path": "readme.txt"}`）；
3. 触发原因（"破坏性操作不可逆，必须人工批准"）；
4. 记录 id 与时间（与审计日志对得上）；
5. **并排的批准/拒绝按钮**——拒绝必须和批准一样容易点。

Web 端 Agent 用 interactive 策略运行（`scripts/03_web.py`）：危险操作生成
pending → SSE 推 `pending` 事件 → 卡片出现 → 用户点批准 → Agent 线程的轮询
感知到状态变化继续执行。CLI 端等价路径：`--policy interactive` 在 tty 下逐条问。

## 5. 打断点该设计在哪一层

```
LLM tool_call
  → 策略层判定 need_approval   ← 打断点①（本课实现的位置）
  → 审批闸门（pending / 问人）
  → 物理执行
```

放在策略层而不是物理层的原因：审批结果要能**跳过整个执行**（deny 时工具函数
根本不会被调用），并且审批记录里能拿到策略上下文（level/reason）。
另一个可选打断点是"计划级"（整份计划先给人看再执行，见 02 教程
LangGraph `__interrupt__`）——适合步骤少、计划稳定的场景；本课的
"操作级"打断点适合 ReAct 这种步骤不可预知的循环，两者可以叠加。

## 思考题

1. 审批等待 60 秒超时后记录变成 expired。如果业务上"这个删除必须今晚完成"，
   超时策略应该怎么调？直接把 wait 拉长到 12 小时合理吗？
2. 为什么拒绝而不是"跳过该工具继续执行后续步骤"？

### 参考答案

1. 不合理。拉长等待 = 批准窗口变大 = 风险敞口变大，而且占用运行线程。
   正确做法是**解耦**：把 destructive 请求写成"待办"持久化，Agent 当次运行
   直接结束并告知用户"删除任务已挂起，明早在审批面板处理"；第二天审批通过后
   由独立执行器（带着原 run_id 的审计上下文）单独执行。审批不应阻塞长任务，
   也不该因为"等不到人"就悄悄降级成执行。
2. 跳过继续执行看似"更流畅"，但后续步骤可能建立在"删除已完成"的假设上
   （先删旧文件再写新文件），静默跳过会产生不一致状态。拒绝回填让 LLM
   显式得知失败并重新规划（或向用户确认），失败要**响亮**，这是安全层的原则。

*上一课：[03 权限分级与沙箱](03-permissions-sandbox.md) | 下一课：[05 审计与红队演练](05-audit-redteam.md)*
