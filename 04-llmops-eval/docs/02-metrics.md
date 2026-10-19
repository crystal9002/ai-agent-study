# 02 · 指标体系：硬指标与软指标

代码：`llmops/metrics.py`、`llmops/judge.py`、`llmops/runner.py`

## 分层打分：每层有自己的指标

RAG / Agent 都是流水线，端到端一个"对/错"无法归因。本教程的分层：

```
问题 ──→ 检索层 ──→ 生成层 ──→ (Agent: 工具层)
         hit@k        containment
         precision@k  faithfulness (judge)
         mrr          relevance (judge)
```

**每层指标独立算，badcase 才能二分定位**：检索层挂了调召回，检索对了生成挂了调 prompt——这是 01 RAG 教程调试心法的指标化。

## 检索层指标（`llmops/metrics.py`）

| 指标 | 定义 | 回答的问题 |
|------|------|-----------|
| `hit@k` | Top-k 内是否出现任一期望 chunk | 该找到的东西找到了吗（0/1） |
| `precision@k` | Top-k 中相关内容占比 | 找到的东西里有多少是噪音 |
| `mrr` | 1/首个命中排名 | 正确答案排得够不够靠前 |

本教程用子串匹配近似"相关性"（`_hit_positions`），教学简化；生产里 expected chunk 用 chunk_id 精确对齐。k 取 3 是因为 LLM prompt 通常只塞得下 3~5 个 chunk——**k 要和你实际送进生成层的 chunk 数一致**，hit@10 意义不大。

`precision@3` 本教程只有 0.3 左右——因为 top-3 平均只命中 1 个相关 chunk。这指标不是越接近 1 越好（k 固定时接近 1 意味着检索"保守"），重点是**跨版本对比**：调了召回参数后 precision 掉了但 hit 没涨，说明召回变"散"了。

## 生成层指标

**硬指标 `containment`**：答案包含全部 `expected_answer_contains` 关键串。便宜、快、可重复，适合 CI 门禁；缺点是死板——"每月 29 元"和"29 元/月"都能过，但"约 30 元"过不了，而后者其实没错。

**软指标 LLM-as-judge**：忠实度（答案 vs 证据）与相关性（答案 vs 问题）各 1~5 分，见 [03 · LLM-as-judge](03-llm-as-judge.md)。能捕捉语义正确性，但有成本、有噪声、可能有偏差。

取舍经验：

| 场景 | 用什么 |
|------|--------|
| PR 门禁（每次提交必跑） | 硬指标，秒级、免费 |
| 发版前评估 | 硬指标 + judge 双轨 |
| 线上抽检 | judge（人没空逐条看） |

## Agent 层指标（`run_agent_case`）

Agent 评估三条腿：

1. **任务成功率** = `tools_ok ∧ answer_ok ∧ turns_ok`（`passed` 字段）
2. **工具选择正确率** `tools_ok`：`must_call_tools ⊆ 实际调用`——过程断言，防"蒙对"
3. **轮次成本** `turns`：平均轮次直接乘 LLM 单价就是成本差异

`metrics.turns` 聚合进报告后，`04_report.py` 对比两次运行时能直接看到"换模型后轮次从 2.1 涨到 3.4"这类退化——**成功率没变但成本涨了 60%，也是回归**。

## 聚合成 report（`aggregate()`）

单条用例 → `case_report()` 统一结构 → `aggregate()` 出 run 级报告：

```python
{"pass_rate": 1.0, "metrics": {"hit@3": 1.0, "containment": 1.0},
 "judge": {"faithfulness": 5.0, "relevance": 4.78}, "judge_coverage": 1.0}
```

两个细节：

- **judge 降级为 None 不计入均分**：judge 失败的用例不会把均分拉低（否则 API 抖动 = 指标暴跌的假回归）。`judge_coverage` 单独暴露 judge 成功率，低于 90% 说明裁判本身不可信。
- **只聚合数值字段**：judge 结果里混了 `reasons` 文本，聚合前按 `isinstance(v, (int, float))` 过滤——解析健壮性要贯穿到聚合层。

## 代码对应

| 文件 | 职责 |
|------|------|
| `metrics.py` | containment / regex_match / hit@k / precision@k / mrr / case_report / aggregate |
| `judge.py` | 忠实度、相关性两维 1~5 分（下一课展开） |
| `runner.py` | `run_rag_case` 把检索/生成指标组装；`run_agent_case` 组装工具/答案/轮次断言 |

## 生产要点

- **先硬后软**：硬指标挂了 judge 也救不回来；先让 containment/hit 达标，再用 judge 挑语义毛病。
- **指标要配基线和阈值**：`pass_rate < 0.9` 阻断上线，`judge_relevance < 3.5` 触发人工复核——没有阈值的仪表盘只是装饰。
- **延迟也是指标**：`avg_latency_ms` 已进 report。质量涨了但 P95 翻倍，用户感知大概率是变差。
- **警惕指标博弈**：containment 只查关键串，模型学会把关键串堆进答案但逻辑不通——所以硬软指标要同时看，单指标优化必翻车。

## 思考题

1. 为什么 hit@k 的 k 建议取"实际送进生成层的 chunk 数"，而不是固定 10？
2. judge 失败降级为 None、不计入均分，可能掩盖什么问题？
3. Agent 评估如果只看 `answer_ok`，哪两类线上事故测不出来？

## 参考答案

1. 生成层只消费 top-k 个 chunk，k 之后的命中对答案毫无贡献。hit@10 高而 hit@3 低，说明正确的资料排在生成层根本看不到的位置——这正是要修的 bug，指标却显示"还行"。
2. 掩盖"judge 系统性失效"——比如换了 prompt 后 judge 解析成功率从 100% 掉到 20%，均分只基于剩下 20% 的用例，看似平稳实则统计意义崩塌。所以 `judge_coverage` 必须和均分一起看，本教程把它单独列出来就是这个原因。
3. ①工具链错误但碰巧答对（该查资料的直接 hallucinate，下次同类问题就翻车）；②成本失控（平均轮次翻倍、重复调用同一工具），答案对但每次请求烧双倍 token，长期跑不经济。

## 下一步

[03 · LLM-as-Judge：提示词、校准与陷阱](03-llm-as-judge.md)
