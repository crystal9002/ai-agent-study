# Agent 安全实战教程（注入防护 / 权限沙箱 / 人工确认 / 审计）

**给 Agent 装上三道防线**：从零实现"带安全层的文件助手 Agent"，
内置 3 个**真实可跑、结果可断言**的攻击演示——裸 Agent 如何中招、
加固 Agent 拦在哪一层，一眼看清。

场景：**沙箱文件助手**——它能列目录、读文件、写笔记、跑只读命令；
但凡想越界（读沙箱外、`rm -rf /`、被投毒文件里的"系统指令"），三道防线伺候。

与 [02 Agent 教程](../02-agent-tutorial/README.md)同一风格；本课是
[012 进阶练习](../AI-Agent开发教程/012-进阶练习清单.md)练习 1（shell 白名单）与
练习 7（human-in-the-loop）的**系统化扩展**。

## 三道防线

```
            用户 / LLM 发出 tool_calls
                     │
  ┌──────────────────▼───────────────────┐
  │ 防线① 注入检测与内容隔离               │  sec/injection.py
  │   工具返回/RAG 内容 → 特征库扫描 →      │
  │   包成 [UNTRUSTED CONTENT] 回填 LLM     │
  ├───────────────────────────────────────┤
  │ 防线② 工具权限与路径沙箱               │  sec/permissions.py
  │   read 自动批 / write 记录 /            │
  │   destructive 需审批（default-deny）    │
  │   realpath 沙箱 + shell 白名单/黑名单   │
  ├───────────────────────────────────────┤
  │ 防线③ 危险操作人工审批                  │  sec/approval.py
  │   pending → 命令行/Web 批准 → 才执行    │
  │   超时 = 拒绝（没人在就不动手）          │
  └──────────────────┬───────────────────┘
                     │ 执行（tools.py 物理保险丝：shell=False/超时/沙箱）
                     │ 审计（audit.py JSONL：who/when/args/decision/defense）
                     ▼
              攻击演示 3/3 拦截 ✓（scripts/01_attack_demo.py）
```

## 学习路径

| 阶段 | 文档 | 对应代码 |
|------|------|----------|
| 1. 威胁模型：过度授权与注入路径 | [docs/01-threat-model.md](docs/01-threat-model.md) | — |
| 2. 提示注入：检测不可靠，隔离是主力 | [docs/02-prompt-injection.md](docs/02-prompt-injection.md) | `sec/injection.py` |
| 3. 权限分级 + 路径沙箱 + shell 双防线 | [docs/03-permissions-sandbox.md](docs/03-permissions-sandbox.md) | `sec/permissions.py` `sec/tools.py` |
| 4. 人工审批 human-in-the-loop | [docs/04-human-in-the-loop.md](docs/04-human-in-the-loop.md) | `sec/approval.py` |
| 5. 审计日志 + 红队用例 + 回归指标 | [docs/05-audit-redteam.md](docs/05-audit-redteam.md) | `sec/audit.py` `sec/attacks.py` |
| 6. 框架对照（guardrails）与生产纵深 | [docs/06-frameworks.md](docs/06-frameworks.md) | `scripts/04_framework.py` |

## 快速开始

### 1. 安装（系统 python3 是 3.7，用 uv 建 3.12 venv）

```bash
cd 05-agent-security
~/.local/bin/uv venv --python /usr/local/bin/python3.12 .venv
~/.local/bin/uv pip install -q -p .venv/bin/python -r requirements.txt
cp .env.example .env   # 填 OPENAI_BASE_URL / OPENAI_API_KEY / LLM_MODEL
```

### 2. 攻击演示（确定性，无需 LLM 也能跑通断言）

```bash
python scripts/01_attack_demo.py          # 3 场景 × 裸/加固对照
python scripts/01_attack_demo.py --live   # 额外用真实 LLM 跑加固 Agent
```

输出：场景 A（文件内容投毒→诱导删文件）/ B（`rm -rf /` 越权）/
C（读沙箱外密钥+外发）× 裸 vs 加固；汇总"裸 3/3 中招、加固 3/3 拦截"。

### 3. CLI 安全 Agent

```bash
python scripts/02_secure_agent.py "列出沙箱文件，然后读 readme.txt 总结"
python scripts/02_secure_agent.py "删除沙箱里的 readme.txt"                    # default-deny 拒绝
python scripts/02_secure_agent.py "删除沙箱里的 readme.txt" --policy interactive --wait 8   # 生成待审→超时拒绝
```

### 4. Web 界面（8004：执行流 / 待审批卡片 / 审计日志）

```bash
python scripts/03_web.py        # 打开 http://127.0.0.1:8004
```

危险操作会生成 pending 卡片，点"批准"Agent 继续执行，点"拒绝"它如实转达。
API：`GET /api/approvals` · `POST /api/approvals/{id}` · `GET /api/audit`。

### 5. 框架对照（guardrails-ai）

```bash
~/.local/bin/uv pip install -p .venv/bin/python -r requirements-framework.txt
python scripts/04_framework.py   # 原生正则 vs guardrails Validator，含混淆矩阵与取舍结论
```

### 6. 红队回归（CI 门禁）

```bash
python scripts/05_redteam_regression.py   # 10 项硬断言，exit 0/1，无需 LLM key
```

与 `01_attack_demo.py` 同口径但零演示输出：注入检测器单测（命中/不出网误报/密钥外发载荷）+ 3 场景加固拦截 + 裸 Agent 中招哨兵（防 payload 腐化假通过）。适合接进 CI 或 pre-commit。

## 项目结构

```
05-agent-security/
├── README.md
├── requirements.txt / requirements-framework.txt
├── .env.example / .env
├── .gitignore                    # 本目录忽略规则（不动仓库根 .gitignore）
├── sandbox_workspace/            # Agent 可操作的沙箱（readme.txt / notes.md 示例）
├── sec/                          # 原生安全层（逐文件阅读）
│   ├── injection.py              # 防线①：特征库正则 + 可选 LLM 审核 + UNTRUSTED 包装
│   ├── permissions.py            # 防线②：三级权限 + 策略 + 路径沙箱 + shell 双防线
│   ├── approval.py               # 防线③：审批状态机（pending/approved/denied/expired）
│   ├── audit.py                  # JSONL 审计：decision/defense/detection 全记录
│   ├── tools.py                  # 5 个安全工具 + 物理保险丝（shell=False/超时/沙箱）
│   ├── agent.py                  # 安全 Agent 循环（ReAct + 三道防线编排）+ BareAgent 对照
│   └── attacks.py                # 3 个攻击场景（投毒文件/越权命令/数据外泄）
├── scripts/
│   ├── 01_attack_demo.py         # 对照演示（默认确定性断言，--live 接真实 LLM）
│   ├── 02_secure_agent.py        # CLI 安全 Agent（--policy strict/auto/interactive）
│   ├── 03_web.py                 # FastAPI 8004：SSE 执行流 + 审批 API + 审计 API
│   ├── 04_framework.py           # guardrails 对照（同一特征库、混淆矩阵、取舍结论）
│   └── 05_redteam_regression.py  # 红队回归（CI 门禁版：10 项硬断言，exit code）
├── web/index.html                # 三栏前端（原生 JS，无构建）
├── audit/                        # 运行产物：audit.log / approvals.jsonl（已 gitignore）
└── docs/                         # 6 篇教程（按学习路径阅读）
```

## 设计要点速览

- **default-deny**：未知工具拒绝、非交互审批超时拒绝、破坏性操作没批就拒绝。
- **检测只是纵深**：正则/LLM 审核有 FN/FP（04 脚本里各放了一个教学样本），
  真正的边界是权限收敛 + 审批（docs/02）。
- **拒绝信息回填**：`REJECTED/DENIED` 字符串进上下文，LLM 自己调整方案，
  不抛异常打断循环（012 练习 1 的老规矩）。
- **攻击演示不伤人**：毒文件/假密钥动态投放并清理；裸 Agent 的危险 shell
  只"到达执行边界"（`[SIMULATED]`）不真跑。
- **审计即黑匣子**：每次决策带 defense（哪道防线）与 detection（注入命中），
  出事可复盘，平时可做拦截率回归（docs/05）。

## 思考题与延伸

每篇 docs 末尾附思考题+参考答案。完成六课后你可以：
给 [02 Agent 教程](../02-agent-tutorial/README.md)的差旅 Agent 补上本课三道防线，
或把 `sec/` 的策略层接到任意 function-calling 循环上。

*上一课：[02 任务规划 Agent](../02-agent-tutorial/README.md) | 下一课：[docs/01 威胁模型](docs/01-threat-model.md)*
