"""迷你知识库：内嵌的产品 FAQ 文档 + 纯关键词检索。

不依赖 torch / 向量库——MCP 教程的重点是"协议接入"，检索质量够用即可。
同一份数据同时被两处使用：
  - mcpd/server.py  → 包装成 MCP 工具 search_kb（给 MCP Agent 用）
  - multi/agents.py → 作为检索 Worker 的本地工具（给多智能体用）
"""
from __future__ import annotations

KB_DOCS = [
    {
        "title": "产品版本与定价",
        "content": (
            "产品共三个版本：免费版 0 元，限 3 人使用，只有基础功能；"
            "团队版 29 元/人/月，最多 50 人，含全部核心功能与优先技术支持；"
            "企业版 99 元/人/月，不限人数，额外提供 SSO 单点登录、审计日志、"
            "专属客户成功经理和 SLA 保障。"
        ),
    },
    {
        "title": "折扣与付费方式",
        "content": (
            "月付无折扣；年付享 8.5 折（团队版折后约 24.65 元/人/月）。"
            "10 人以上首次采购可联系销售申请试用延长；"
            "教育与非营利组织凭资质可申请 5 折。"
        ),
    },
    {
        "title": "团队版功能清单",
        "content": (
            "团队版包含：共享工作区、成员角色管理（管理员/成员两级）、"
            "每月 2000 次 API 调用额度、工单优先支持（4 小时响应）、"
            "数据导出。不含审计日志与 SSO（需企业版）。"
        ),
    },
    {
        "title": "企业版能力与服务",
        "content": (
            "企业版在团队版之上增加：不限人数、SSO（SAML/OIDC）、"
            "完整审计日志、99.9% SLA、专属客户成功经理、"
            "私有化部署可选（另计费用，按节点数报价）。"
        ),
    },
    {
        "title": "退换与账单",
        "content": (
            "按月订阅可随时取消，当期不退；年付在首 30 天内可全额退款，"
            "超过 30 天按剩余月份比例退款。账单支持对公转账与主流信用卡，"
            "可开具增值税专用发票。"
        ),
    },
]

# 检索词表：命中 query 与文档两侧才计分（简易倒排，够教程演示）
_TERMS = [
    "免费版", "团队版", "企业版", "定价", "价格", "多少钱", "费用", "元",
    "人数", "上限", "折扣", "年付", "月付", "试用", "教育", "功能",
    "支持", "sla", "sso", "审计", "部署", "退", "发票", "api", "额度",
]


def search_kb(query: str, top_k: int = 2) -> dict:
    """纯关键词检索：按命中词数打分，返回最相关的文档。"""
    q = query.lower()
    scored: list[tuple[int, dict]] = []
    for doc in KB_DOCS:
        text = (doc["title"] + doc["content"]).lower()
        score = sum(1 for t in _TERMS if t in q and t in text)
        # query 中连续 2 字以上的片段直接匹配也算分（兜底未登录词）
        for i in range(len(q) - 1):
            if q[i : i + 2] in text and q[i : i + 2] in q:
                score += 0.5
        if score > 0:
            scored.append((score, doc))
    scored.sort(key=lambda x: -x[0])
    hits = [d for _, d in scored[:top_k]]
    return {
        "query": query,
        "hits": hits,
        "total": len(scored),
        "note": "命中 0 条时建议换用更具体的关键词（如 版本名/人数/折扣）",
    }
