"""LLM-as-Judge：faithfulness（答案 vs 证据）与 relevance（答案 vs 问题），1~5 分。

健壮性三板斧（对应 docs/03-llm-as-judge.md）：
1. 提示词强制输出 JSON：{"score": n, "reason": "..."}
2. 解析失败自动重试（默认 2 次）
3. 仍失败则返回 None（降级），评估不中断，聚合时自动跳过 None
"""
from __future__ import annotations

import json
import re

from llmops.llm import chat
from llmops.trace import Trace

JUDGE_SYSTEM = (
    "你是一个严格的 LLM 应用评估裁判。只输出一个 JSON 对象，不要输出任何其他文字，"
    '格式：{"score": <1-5 的整数>, "reason": "<不超过50字的中文理由>"}'
)

FAITHFULNESS_USER = """请评估【答案】是否忠实于【证据】——答案中的事实是否都能在证据中找到支持，有无编造。

【证据】
{evidence}

【问题】
{question}

【答案】
{answer}

评分标准：5=完全忠实且充分利用证据；4=基本忠实，个别表述证据未直接支持；3=部分编造或张冠李戴；
2=大部分内容无证据支持；1=与证据完全矛盾或纯属编造。"""

RELEVANCE_USER = """请评估【答案】与【问题】的相关性——是否正面回应了问题、详略得当、无跑题。

【问题】
{question}

【答案】
{answer}

评分标准：5=精准完整回答；4=回答正确但略冗余或略欠缺；3=回答了部分；2=基本跑题；
1=答非所问。"""


def _extract_json(text: str) -> dict | None:
    """从模型输出中尽力抠出 JSON（容忍 ```json 包裹与前后废话）。"""
    if not text:
        return None
    m = re.search(r"\{.*?\}", text, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or "score" not in obj:
        return None
    try:
        score = int(obj["score"])
    except (TypeError, ValueError):
        return None
    if not 1 <= score <= 5:
        return None
    return {"score": score, "reason": str(obj.get("reason", ""))[:100]}


def judge_score(
    user_prompt: str,
    *,
    model: str | None = None,
    retries: int = 2,
    trace: Trace | None = None,
) -> dict | None:
    """带重试与降级的裁判调用。成功返回 {score, reason}，失败返回 None。"""
    messages = [
        {"role": "system", "content": JUDGE_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]
    for _ in range(retries + 1):
        try:
            msg = chat(messages, model=model, temperature=0.0, trace=trace)
            parsed = _extract_json(msg.content or "")
            if parsed is not None:
                return parsed
        except Exception:  # noqa: BLE001 —— API 失败重试，最终降级
            continue
    return None


def faithfulness(question: str, answer: str, evidence: str, **kw) -> dict | None:
    return judge_score(FAITHFULNESS_USER.format(question=question, answer=answer, evidence=evidence), **kw)


def relevance(question: str, answer: str, **kw) -> dict | None:
    return judge_score(RELEVANCE_USER.format(question=question, answer=answer), **kw)


def judge_both(question: str, answer: str, evidence: str, **kw) -> dict | None:
    """一次评两个维度；任一失败则整体降级为 None（保持结构干净）。"""
    f = faithfulness(question, answer, evidence, **kw)
    r = relevance(question, answer, **kw)
    if f is None or r is None:
        return None
    return {"faithfulness": f["score"], "relevance": r["score"], "reasons": {"f": f["reason"], "r": r["reason"]}}
