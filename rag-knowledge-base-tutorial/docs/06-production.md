# 06 · 生产化落地：从 Demo 到上线

本教程的代码是一个**教学用最小实现**。上生产还需补齐以下几块。

## 1. 架构总览

```
                    ┌─────────────────────────────┐
 文档源 ──→ 解析/清洗 ──→ 分块 ──→ Embedding ──→ 向量库
 (OSS/网盘/API)      后台任务(增量)                │
                                    ┌──────────────┤
 用户 ──→ FastAPI ──→ 检索+重排 ◄────┘              │
             │                                    │
             └──→ LLM 网关(限流/降级) ──→ SSE 流式返回
             │
             └──→ 日志/评估/监控 ──→ Bad case 回流
```

## 2. 组件选型（对照本项目迁移）

| 环节 | 教学版（本项目） | 生产版 |
|------|----------------|--------|
| 文档解析 | txt/md | Unstructured / MinerU（PDF、Office、扫描件 OCR） |
| 向量库 | FAISS | **pgvector**（中小规模）/ **Milvus**（大规模）/ Qdrant |
| Embedding | bge-small | **bge-m3** 或托管 API |
| 重排 | bge-reranker-base | **bge-reranker-v2-m3**（中文）/ Cohere |
| LLM | 直连 API | 统一网关：限流、多模型降级、成本核算 |
| 服务 | 命令行 | FastAPI + SSE 流式 + 异步任务(Celery/Arq) |
| 前端 | — | 简单 Web 聊天页（带引用侧栏） |

## 3. 文档解析（最容易被低估的环节）

生产文档 80% 是 PDF/Word/PPT，含表格、图片、页眉页脚。

- 用 **Unstructured** 或 **MinerU** 做版面解析，保住表格与标题结构
- 解析结果带**文档 ID + 版本 + 更新时间**，支持增量索引与删除
- 建 pipeline 质检：解析耗时、字符数、乱码率打点告警
- 文档更新时要**删旧向量再插新向量**（按 doc_id 过滤删除），否则脏数据永远在库里

## 4. 数据模型（以 pgvector 为例）

```sql
CREATE TABLE chunks (
  id          BIGSERIAL PRIMARY KEY,
  doc_id      TEXT NOT NULL,
  version     INT  NOT NULL,
  content     TEXT NOT NULL,
  metadata    JSONB,          -- 标题/章节/租户/时间…
  embedding   VECTOR(1024) NOT NULL
);
CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON chunks USING gin (metadata);
```

要点：**多租户必须带 tenant_id 并在每次检索时强制过滤**（安全边界，不能靠后过滤）。

## 5. 服务层示例（FastAPI + SSE）

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()

@app.post("/chat")
async def chat(q: str):
    def gen():
        for kind, payload in pipeline.query_stream(q):
            yield f"data: {json.dumps({'type': kind, 'data': _ser(payload)}, ensure_ascii=False)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")
```

工程要求：

- **延迟预算**：检索 < 200ms、重排 < 300ms、首字 < 1s；超时与降级（重排超时→跳过重排直接生成）
- **并发**：Embedding 与重排模型用推理服务（TEI / vLLM / Triton）独立部署，别和业务进程混在一起
- **缓存**：相同 query 的检索结果缓存几分钟（TTL），热点问题命中率可观

## 6. 评估与监控（决定上线上限）

**离线评估**（每次改检索/分块参数必跑）：
- 构建 30~50 条 `问题 → 应命中 chunk` 黄金集
- 指标：Hit Rate@k、MRR、端到端答案相关性（LLM-as-Judge）

**在线监控**：
- 延迟分位（P50/P99：检索、重排、生成）
- 无检索结果率、拒答率、用户点踩率、答案引用点击率
- Token 成本按租户/功能拆分

**Bad case 回流闭环**：用户点踩 → 存 query + 检索结果 + 最终答案 → 人工归因（分块问题？召回没到？生成胡说？）→ 修数据或调参 → 回到离线评估。**这个循环是 RAG 系统持续变好的唯一机制。**

## 7. 上线前检查清单

- [ ] 文档解析覆盖 PDF/表格/OCR，解析失败有告警
- [ ] 增量更新：文档删除/改版后旧向量同步清理
- [ ] 多租户隔离在检索层强制过滤
- [ ] 重排分数阈值 + 拒答策略，幻觉压测通过
- [ ] 黄金集离线评估达标，参数变更走回归
- [ ] 流式接口、超时降级、模型服务独立部署
- [ ] 引用溯源展示给用户（可点开看原文）
- [ ] 日志脱敏（用户 query 不落敏感信息）
- [ ] 成本看板（Token + 算力）

## 8. 建议的课后实践

1. **最小 Web 版**：给 `query_stream()` 套 FastAPI SSE + 一个单页 HTML 聊天界面
2. **混合调优**：给 RRF 加通道权重（向量/BM25 不对等），或换 jieba 分词对比 BM25 效果
3. **换库练习**：框架版已内置 `VECTOR_STORE=pgvector`（04/05，连接串 `PG_CONN`）；原生版把 `SqliteVectorStore` 的 SQL 换成 pgvector，验证接口不变
4. **评估脚本**：写 `scripts/04_eval.py`，对黄金集计算 Hit Rate@k
5. **查询改写**：在 `retrieve()` 前加一步 LLM 改写，对比效果差异
