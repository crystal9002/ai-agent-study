# 05 · 生成：Prompt 设计与引用溯源

代码：`rag/llm.py`、`rag/pipeline.py`（SYSTEM_PROMPT / USER_TEMPLATE / build_prompt）

## Prompt 结构（本项目模板）

```
SYSTEM:  规则约束 —— 只依据资料、标注引用 [n]、资料不足要明说、中文简洁
USER:    【知识库资料】
           [1]（来源：product_manual）…
           [2]（来源：faq）…
         【用户问题】
         团队版多少钱？
```

三个要素缺一不可：

1. **限定来源**："只根据资料回答，不要编造"——RAG 压幻觉的主手段。
2. **强制引用**：给每个 chunk 编号 `[1][2]`，要求模型在句末标注。好处不只是可读：**用户能核对，模型"编造引用"也更容易被发现**。
3. **拒答通道**：明确告诉模型"资料不足以回答时就说没有"。这是生成层的幻觉保险，配合 [04](04-retrieval-and-rerank.md) 的重排分数阈值双管齐下。

`build_prompt()` 把检索到的 chunks 渲染成带来源和编号的 context，注意 **chunk 顺序保持重排后的得分降序**——最重要的资料放最前面（LLM 对开头和结尾的内容更敏感）。

## LLM 配置

`rag/llm.py` 走 OpenAI 兼容接口，改 `.env` 即可切换供应商：

```bash
OPENAI_BASE_URL=https://api.deepseek.com/v1   # 或 openai / 通义 / 方舟 / vLLM
LLM_MODEL=deepseek-chat
OPENAI_API_KEY=sk-...
```

- `temperature=0.2`：知识问答要**确定性**，别调高
- **流式输出**（`chat_stream`）：首字延迟从 2~3s 降到几百毫秒，`scripts/03_chat.py` 已接入

## 生成层的进阶手段

| 手段 | 说明 |
|------|------|
| 查询改写 | 用户问题太短/含指代时，先让 LLM 改写成独立完整的检索 query（"它多少钱" → "智能云盘团队版价格"） |
| 多路召回融合 | 改写后的问题各跑一遍检索，结果取并集 |
| 答案后校验 | 生成后再问一次 LLM："答案的每一句能否被资料支持？"，不支持则删 |
| 结构化输出 | 需要前端展示时，让模型输出 `{answer, citations: [{chunk_id, quote}]}` JSON |
| Chat History | 多轮对话要把前几轮 query/answer 拼进 prompt，否则"那它支持吗？"这类指代问题无法检索 |

## 调试心法

`scripts/02_query.py` 会**先打印检索结果再打印回答**——这是 RAG 开发最重要的习惯：

- 检索结果里**没有**正确资料 → 问题在前四步（分块/向量化/召回），调 Prompt 没用
- 检索结果里**有**正确资料但答错 → 才是 Prompt 或模型能力问题

按此二分，90% 的"RAG 效果不好"都能快速定位。

## 下一步

[06 · 生产化落地](06-production.md)
