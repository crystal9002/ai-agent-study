# 06 · 框架对照与生产纵深

## 本课要点

- 框架（guardrails-ai）提供的是**校验基础设施**（结构化结果、on-fail 策略、
  Rail 组合），不提供"安全规则本身"——规则还是你自己写的。
- 取舍：本教程的注入检测用 0 依赖原生实现；需要结构化校验生态时再引入框架。
- 生产纵深远不止进程内三道防线：网关限流、出网代理白名单、密钥隔离、最小权限 IAM。

## 1. 框架对照实录（`scripts/04_framework.py`）

本课实际采用的方案与过程记录：

```bash
# requirements-framework.txt
guardrails-ai>=0.5.0
~/.local/bin/uv pip install -p .venv/bin/python -r requirements-framework.txt
python scripts/04_framework.py
```

实测笔记（踩过的坑，写给要上生产的你）：

1. **安装体积**：guardrails-ai 0.11 连带安装 opentelemetry 全家桶、boto3、
   tokenizers 等 100+ 依赖——对一个"正则扫描"场景明显过重；
2. **遥测**：默认往 OTLP 端点发 trace，离线环境每批 span 重试拖慢启动。
   脚本里 `os.environ.setdefault("OTEL_SDK_DISABLED", "true")` 必须在
   import guardrails **之前**设置；
3. **内置 validators 已搬进 hub**（需 `guardrails hub install` 联网安装），
   本课用自定义 `Validator` 复用 `sec/injection.py` 特征库；
4. **on-fail 策略**是框架真正的增值：`refrain`（返回 None 拦断）、
   `exception`（抛出）、`fix_value`（修正后放行）——同一份规则可以有
   三种失败语义，原生实现要自己写这些分支。

04 脚本的对照结论（含标注样本集的混淆矩阵）：

| 方案 | 判定结果 | 结构化报告 | 依赖 |
|------|----------|-----------|------|
| 原生 `injection.scan` | 与框架一致（同一特征库） | 命中列表（自拼） | 0（openai/dotenv 之外） |
| guardrails Validator | 一致 | validation_summaries 完整 | 100+ 包 |

**取舍建议**：检测层规则简单 → 原生 0 依赖更合适；要做结构化输出校验、
多轮 reask、团队统一 Rail 规范 → 再引入 guardrails。

**降级方案**（若 guardrails 装不上/过重）：把 04 脚本的第二路换成
"LLM 审核层最小实现"——即 `injection.LLMReviewer`（`INJECTION_LLM_REVIEW=1`），
对照"纯正则 vs 正则+LLM 复核"的漏报/误报变化。两条路都实跑过才算完成本课。

## 2. 生产纵深：进程外还有四层

本教程的三道防线在**一个进程内**。生产环境攻击者一旦拿到 shell 或进程权限，
进程内防线全部失效——纵深要向外扩展：

```
用户 → API 网关（鉴权/限流/审计）→ Agent 进程（三道防线）
                                        │
              密钥隔离（进程读不到明文 Key）
                                        │
              出网代理（白名单域名 + DLP）→ 外部世界
                                        │
              云 IAM / 容器（最小权限、只读挂载、无 sudo）
```

| 层 | 措施 | 对应本课 |
|----|------|----------|
| 网关层 | 每任务工具调用次数上限、QPS 限流、Token 预算 | max_iters 的进程外版本 |
| 出网 | 代理白名单只放行业务域名；禁止直连 IP；DNS 过滤 | run_shell 的 egress 黑名单 |
| 密钥 | Key 放密钥服务，短时租约注入；工具返回/日志脱敏 | `scan_outbound` 的生产版 |
| IAM/OS | 容器非 root、沙箱目录只读挂载、无 Docker socket | PathSandbox 的 OS 级版本 |
| 网络 | Agent 容器放独立 VPC，默认无出网路由 | "物理保险丝"的终极形态 |

原则与进程内一致：**每一层都假设内层已被攻破**。检测层可以漏，权限层可以被
绕过一次，但网关限流 + 出网白名单 + OS 最小权限让每次突破的收益递减。

## 3. 落地清单（上线前过一遍）

- [ ] 工具权限表评审：每个工具的级别是否最小？
- [ ] default-deny 生效：未知工具/非交互审批超时都是拒绝？
- [ ] 沙箱目录 OS 级隔离：容器只读挂载 + 独立 volume？
- [ ] 出网白名单：Agent 所在环境默认无出网？
- [ ] 密钥不进上下文：模型与工具都拿不到明文 Key？
- [ ] 审计全量落盘 + 敏感串打码；日志访问权限收紧？
- [ ] 红队用例进 CI：`01_attack_demo.py` + 正常任务不误拦截测试？
- [ ] 审批通道有人值守：pending 有超时、有告警、有值班响应？

## 思考题

1. 为什么"框架内置了安全校验"不等于"用了框架就安全"？
2. 你的 Agent 需要调用公司内部订单系统。对照第 2 节的纵深表，
   给出至少三个进程外控制点。

### 参考答案

1. 框架给的是执行机制（何时校验、失败怎么办、结果怎么报告），**规则集与
   权限模型仍要你自己定义**。guardrails 的内置 validators 搬到 hub 后更明显：
   装了库 ≠ 装了规则；就算规则全了，"检测"层的天花板也在 docs/02 讲过——
   框架不会替你做权限收敛和人工审批。把安全外包给框架的心态本身就是漏洞。
2. 例如：(a) 网关侧按 Agent 身份发短时 Token，订单系统按 Token 限权
   （只能查单不能改单）；(b) 出网白名单只放行订单系统域名，且订单系统侧
   只接受来自 Agent 服务账号的调用（双向认证）；(c) 审计在订单系统侧
   也记一份（调用方日志 ≠ 服务方日志，对账才能发现异常）；
   (d) 改单类接口在订单系统侧再做一次幂等 + 金额阈值人工复核，
   即使 Agent 侧全被绕过也有最后闸门。

*上一课：[05 审计与红队](05-audit-redteam.md) | 课程完结 · 回到 [README](../README.md)*
