"""被测 RAG 管线（教学用最小实现）：关键词假检索 + 真 LLM 生成。

检索不用 torch/HF 向量模型——用"查询字符与 chunk 的重合度"做打分排序，
足以演示 hit@k / precision@k 与端到端评估；真实项目把 retrieve() 换成
01 教程的混合召回即可（接口不变：retrieve(query, k) -> [chunk dict]）。
"""
from __future__ import annotations

from llmops.llm import chat
from llmops.trace import Trace

# 内置小语料（模拟一个"智能云盘"产品文档库，与 01 教程场景同款）
CORPUS: list[dict] = [
    {"id": "pricing", "source": "product_manual", "content": "智能云盘团队版定价为每位成员每月 29 元，年付按 10 个月计费；企业版支持私有化部署，按需报价。"},
    {"id": "free_tier", "source": "faq", "content": "免费版用户可获得 5 GB 存储空间，单文件上传上限 100 MB，不支持版本历史功能。"},
    {"id": "file_types", "source": "product_manual", "content": "支持上传 doc、docx、pdf、xlsx、pptx、jpg、png、mp4 等常见格式，单文件最大 5 GB（付费版）。"},
    {"id": "sync", "source": "product_manual", "content": "客户端支持 Windows、macOS、iOS、Android 四端实时同步，冲突文件会自动保留两个版本供用户选择。"},
    {"id": "security", "source": "security_doc", "content": "数据采用 AES-256 静态加密与 TLS 1.3 传输加密，并通过 ISO 27001 认证，支持审计日志导出。"},
    {"id": "api_auth", "source": "api_guide", "content": "OpenAPI 使用 Bearer Token 鉴权，请求头携带 Authorization: Bearer <token>，令牌可在控制台创建，有效期最长一年。"},
    {"id": "api_limit", "source": "api_guide", "content": "OpenAPI 默认限流为每分钟 100 次请求，单次列表查询最多返回 200 条记录，超出可通过分页游标获取。"},
    {"id": "recovery", "source": "faq", "content": "删除的文件在回收站保留 30 天，超级管理员可一键恢复；企业版可延长至 90 天。"},
    {"id": "billing_refund", "source": "faq", "content": "年付订单支持 7 天内无理由退款，超过 7 天按剩余月份折算；月付订单不支持退款。"},
    {"id": "sso", "source": "enterprise", "content": "企业版支持 SAML 2.0 与 OIDC 单点登录，可与企业微信、飞书、钉钉目录同步，成员离职自动停用账号。"},
    {"id": "support", "source": "faq", "content": "工作日 9:00-18:00 提供在线客服；企业版客户配备专属技术支持群，7x24 小时紧急响应。"},
    {"id": "transfer", "source": "product_manual", "content": "支持生成外部分享链接，可设置提取码与有效期；付费版支持上传/下载加速通道。"},
]

SYSTEM_PROMPT = (
    "你是智能云盘的客服助手。只根据下面给出的资料回答用户问题，不要编造；"
    "资料不足以回答时明确说'资料中没有相关信息'。回答简洁中文。"
)


def _score(query: str, text: str) -> float:
    """字符重合度打分：查询中的每个字符在文本里出现即累加（教学简化版 BM25 替代）。"""
    q = query.lower()
    t = text.lower()
    return sum(t.count(ch) for ch in set(q) if ch.strip())


def retrieve(query: str, k: int = 3) -> list[dict]:
    """关键词假检索：按字符重合度排序返回 top-k chunks。"""
    scored = []
    for c in CORPUS:
        s = _score(query, c["content"]) + 2 * _score(query, c["id"]) + _score(query, c["source"])
        scored.append((s, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for s, c in scored[:k] if s > 0]


def generate(question: str, chunks: list[dict], trace: Trace | None = None) -> str:
    """基于检索结果生成答案（真 LLM；trace 记 token）。"""
    context = "\n".join(f"[{i+1}]（来源：{c['source']}）{c['content']}" for i, c in enumerate(chunks))
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"【资料】\n{context}\n\n【问题】\n{question}"},
    ]
    msg = chat(messages, temperature=0.2, trace=trace)
    return (msg.content or "").strip()


def rag_query(question: str, k: int = 3, trace: Trace | None = None) -> dict:
    """完整一问：检索 + 生成。返回 {answer, retrieved: [chunk...]}。"""
    chunks = retrieve(question, k=k)
    answer = generate(question, chunks, trace=trace)
    return {"answer": answer, "retrieved": chunks}
