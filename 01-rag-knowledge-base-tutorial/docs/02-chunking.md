# 02 · 分块（Chunking）：RAG 质量的第一道关卡

代码：`rag/chunker.py`

## 为什么分块决定检索质量

Embedding 模型对**过长文本**的向量表达会"平均化"——一篇 5000 字的文章压成一个向量，什么都像、什么都不精。分块就是把文档切成"一个向量能准确代表"的小单元。

| 块太大 | 块太小 |
|--------|--------|
| 向量语义模糊，检索不精准 | 丢失上下文，答案不完整 |
| 噪声多，浪费 LLM 上下文窗口 | 引用碎片化，可读性差 |

## 本教程的分块策略：递归切分 + 重叠窗口

`chunk_text()` 的实现分三步：

1. **按分隔符优先级递归切**：`\n\n`（段落）→ `\n`（换行）→ `。`（句子）→ 硬切。优先在语义边界断开。
2. **过长段落按句子二次切**：`_split_long()` 保证每块 ≤ `chunk_size`。
3. **重叠窗口**：相邻块共享 `overlap` 个字符，缓解"答案刚好被切断在边界"的问题。

```python
chunks = chunk_text(text, doc_id="doc1", chunk_size=512, overlap=64)
```

## 参数怎么调

| 场景 | chunk_size | overlap |
|------|-----------|---------|
| 中文通用（本教程默认） | 400~600 | 50~100 |
| FAQ / 问答对 | 200~300 | 30~50 |
| 法律法规、长篇技术文档 | 600~1000 | 100~150 |

经验值：**chunk 长度 ≈ 查询长度的 3~10 倍**。用户问一句话（10~30 字），检索单元在 100~500 字通常最合适。

## 生产中更讲究的策略

1. **结构感知分块**：Markdown 按标题层级切（`#` 下的所有内容归属该标题），表格不切断。LlamaIndex/LangChain 的 `MarkdownSplitter` 即此思路。
2. **父子块（Small-to-Big）**：检索用小块（精准命中），返回给 LLM 用它所属的大块（上下文完整）。
3. **语义分块**：计算相邻句子的 embedding 相似度，在相似度骤降处（话题转换）切分。
4. **问答对优化**：FAQ 类文档直接把「Q+A」作为独立 chunk，检索命中率最高——本项目 `data/faq.md` 就适合这种切法。
5. **切完必查元数据**：每个 chunk 带上 `doc_id`、标题、章节，生成回答时才能给出可信引用（`pipeline.build_prompt()` 已在用）。

## 切换分块方式（本项目支持 3 种策略）

`chunk_text(..., strategy=...)`，或用配置切换（改完**必须重建索引**）：

| 策略 | 做法 | 适用场景 |
|------|------|----------|
| `recursive`（默认） | 段落 → 句子 → 硬切递归 | 通用，任何文本 |
| `markdown` | 按 `#` 标题切章节，超长章节递归兜底 | Markdown 文档（本教程 `data/` 即是），chunk 自带标题上下文 |
| `sentence` | 句子序列滑窗 | FAQ 问答对、字幕等短文本密集语料 |

```bash
# 方式一：命令行
python scripts/01_build_index.py --strategy markdown

# 方式二：环境变量（.env）
CHUNK_STRATEGY=markdown
python scripts/01_build_index.py

# 方式三：代码
RAGPipeline(chunk_strategy="sentence")
```

切换后运行 `01_build_index.py` 重建 `index/` 即生效——**换策略/换分块参数/换 Embedding 模型都必须全量重建**，否则向量与文本错位。生产上建议对不同策略各跑一遍评估集（见 [04](04-retrieval-and-rerank.md)），用 Hit Rate@k 决策，而不是凭感觉。

## 常见坑


- **表格/代码被腰斩** → 检测 Markdown 表格与代码块，作为原子单元不参与切分。
- **多文件重复内容** → 灌库前做去重（MinHash/精确哈希），否则 top-k 全是重复块。
- **扫描版 PDF 是图片** → 必须先 OCR，否则加载到的是乱码或空文本。

## 下一步

[03 · Embedding 与向量库](03-embedding-and-vector-db.md)
