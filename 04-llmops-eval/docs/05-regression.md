# 05 · 回归流程与 Badcase 回流

代码：`scripts/04_report.py`、`llmops/store.py`

## 回归检测的标准循环

```
改 prompt / 换模型 / 调参数
        │
        ▼
跑 golden set（02_eval_rag.py / 03_eval_agent.py）
        │ 新 run 落盘 + 登记 index
        ▼
对比报告（04_report.py：旧 vs 新，逐指标 diff）
        │
   ┌────┴─────┐
   ▼          ▼
 指标持平/提升   🔴 回归
   │          │
 合入          看 badcase 明细 → 归因 → 修复 → 重跑
```

没有这一圈的"优化"都是玄学。`04_report.py` 把这圈的最后两步做成了工具。

## 04_report.py 的三件事

**① 趋势**：读 `index.jsonl` 列出全部同类运行，旧 → 新排：

```
═══ eval_rag 趋势（3 次，旧 → 新）═══
  2026-10-19 02:03:51  …-344705  pass_rate=100.0%  hit@3=1.0  faithfulness=5.0
  2026-10-19 02:05:38  …-568f5c  pass_rate=100.0%  hit@3=1.0  faithfulness=5.0
```

**② diff**：默认取最近两次同类评估，逐指标相减：

```
  指标                旧        新        Δ      判定
  pass_rate        0.8750   1.0000  +0.1250  🟢 提升
  tools_ok         1.0000   1.0000  +0.0000  ≈ 持平
```

**③ 回归判定**：下降超过 `REGRESSION_THRESHOLD`（默认 0.05，`.env` 可改）标 🔴。实测中 agent 评估修复 agent-03 断言后就是上面这组数据——golden set 校准本身也走回归循环。

阈值怎么定：**硬指标 0.05~0.1**（12 条用例里波动 1 条 ≈ 0.08）；**judge 分 0.3~0.5**（裁判本身有 ±0.2 的噪声，定太紧会天天误报）。judge 单维下降半分以内属于正常抖动，别当回归处理。

## 明确指定对比（改前存个 run_id）

```bash
.venv/bin/python scripts/02_eval_rag.py   # 改动前：记下 run_id A
# ……改 prompt……
.venv/bin/python scripts/02_eval_rag.py   # 改动后：run_id B
.venv/bin/python scripts/04_report.py --old A --new B
```

自动化流水线里就是这么接：CI 每次跑评估，把新 run 和 main 分支最后一次 run 对比，🔴 则阻断合并。

## Badcase 回流闭环

diff 发现回归后，看明细：

```bash
cat runs/<run_id>.cases.json | .venv/bin/python -m json.tool | less
# 或打开 Web 仪表盘，点开该次运行的"用例明细"
```

逐条归因，每条 badcase 只有一个结论：

| 现象 | 归因 | 动作 |
|------|------|------|
| 检索没召回期望 chunk | 召回/分块问题 | 调检索参数；该 chunk 的问法补进 golden set |
| 检索到了但答案错 | prompt/模型问题 | 改 prompt，重跑回归 |
| 答案对但断言挂 | **用例太 brittle** | 修 golden set（本教程 agent-03 就是实例） |
| 对抗用例编造 | 幻觉防线失效 | 加强拒答 prompt + 对抗样本扩充 |
| judge 分低但人看着对 | 裁判刻度偏了 | 修 judge 提示词，重新校准（03 课） |

**agent-03 的真实经历**：`get_time` 返回 `2026-10-19`，模型转写成"2026年10月19日"，`success_regex: \d{4}-\d{2}-\d{2}` 判失败。这不是系统退化，是断言没跟上模型的正常表达。修复：正则放宽为 `(\d{4}[-年]\d{1,2}[-月]\d{1,2})`，重跑即 100%。**评估挂了先分清"系统退化"还是"考题过时"**——两者处理路径完全相反。

归因完成后，badcase（或它的变体）**必须回流进 golden set**——这就是第 01 课说"golden set 是活的"的具体含义：

```jsonl
// 下次评估加上这类用例，防止同一坑反复踩
{"id": "rag-13", "type": "qa", "question": "<新发现的问法>", ...}
```

## 代码对应

| 符号 | 职责 |
|------|------|
| `04_report.print_trend` | 读 index 出趋势表 |
| `04_report._flatten` | report 摊平成 {指标名: 数值}，嵌套 judge/metrics 拍平 |
| `04_report.diff` | 逐指标相减，阈值判定标 🔴🟢≈ |
| `store.list_runs` / `latest_two_evals` | index 读取与"最近两次同类"定位 |
| `runs/*.cases.json` | 02 脚本落的用例明细，badcase 人工复核入口 |

## 生产要点

- **改前必有基线 run**：回归对比的前提是"改动前最后一次全量评估"。CI 里自动跑，别靠人肉记 run_id。
- **单侧缺失要跳过**：一侧有 judge 一侧没有（如 `--no-judge` 跑的），diff 显示"单侧缺失，跳过"而不是当 0 处理——否则全是假回归。
- **回归 ≠ 不能合**：质量与成本、延迟有 trade-off。新模型 faithfulness +0.2 但轮次 +40%，是否合入是业务决策——报告只负责把 trade-off 摆上台面。
- **回流要脱敏**：生产日志来的 badcase 先脱敏再进 golden set（01 课讲过）。
- **每周清理一次过时用例**：产品改版后题目作废，留着只会制造噪声回归。

## 思考题

1. 为什么 diff 里"单侧缺失"的指标要跳过而不是按 0 参与计算？
2. badcase 显示"答案对了但 passed=False"，第一步该查什么？
3. 阈值 REGRESSION_THRESHOLD 定为 0.01 会有什么后果？

## 参考答案

1. 一侧 None 一侧有值，通常意味着两次评估**配置不同**（比如一边 --no-judge），指标不可比。按 0 算会把"配置差异"误报成"暴跌 100%"的假回归，淹没真实信号；跳过并显式提示，才能让读者注意到配置不一致本身。
2. 先查断言（golden set）而不是查系统。答案内容正确说明管线没问题，失败大概率是 success_regex/expected_contains 与模型的实际表达不匹配（agent-03 实例）。确认是断言问题就修用例重跑，是系统问题才进归因排查——顺序反了会浪费一整轮排查。
3. 12 条用例里随机波动 1 条就是 8.3%，远超 0.01——每次跑都会误报回归，团队很快对 🔴 脱敏（狼来了效应），真正的回归反而被无视。阈值必须大于单次评估的噪声底，小样本场景 0.05~0.1 才合理。

## 下一步

[06 · 生产观测平台：Langfuse 对照与告警](06-production-platform.md)
