"""硬指标（纯 Python，不依赖 LLM）：containment / regex / hit@k / precision@k / MRR。

指标定义（对应 docs/02-metrics.md）：
- containment：答案是否包含全部关键串（最朴素的"答对了吗"）
- regex_match：答案是否命中成功正则（Agent 任务常用）
- hit_at_k：前 k 个检索结果里是否出现任一期望 chunk
- precision_at_k：前 k 个检索结果里命中比例
- mrr：首个命中结果排名的倒数（1/1, 1/2, 1/3…）
"""
from __future__ import annotations

import re
from typing import Iterable, Sequence


def containment(answer: str, expected_contains: Sequence[str]) -> bool:
    """答案包含所有期望串才算通过（大小写不敏感）。"""
    if not expected_contains:
        return True
    a = (answer or "").lower()
    return all(token.lower() in a for token in expected_contains)


def regex_match(answer: str, pattern: str) -> bool:
    """答案命中正则即通过。"""
    if not pattern:
        return True
    try:
        return re.search(pattern, answer or "", re.DOTALL) is not None
    except re.error:
        return False


def _hit_positions(retrieved: Sequence[str], expected: Iterable[str]) -> list[int]:
    """返回每个期望串在检索结果中的最早出现位置（0 起），未命中为 -1。"""
    exp = [e.lower() for e in expected]
    positions = []
    for e in exp:
        pos = -1
        for i, r in enumerate(retrieved):
            if e in r.lower():
                pos = i
                break
        positions.append(pos)
    return positions


def hit_at_k(retrieved: Sequence[str], expected: Sequence[str], k: int = 3) -> bool:
    """Top-k 内命中任一期望 chunk 即为 1。"""
    if not expected:
        return True
    return any(0 <= p < k for p in _hit_positions(retrieved, expected))


def precision_at_k(retrieved: Sequence[str], expected: Sequence[str], k: int = 3) -> float:
    """Top-k 中"相关"结果的比例。用子串匹配近似相关性（教学简化版）。"""
    top = [r.lower() for r in retrieved[:k]]
    if not top:
        return 0.0
    hit = 0
    for r in top:
        if any(e.lower() in r for e in expected):
            hit += 1
    return round(hit / len(top), 4)


def mrr(retrieved: Sequence[str], expected: Sequence[str]) -> float:
    """首个期望命中的倒数排名。"""
    positions = [p for p in _hit_positions(retrieved, expected) if p >= 0]
    if not positions:
        return 0.0
    return round(1.0 / (min(positions) + 1), 4)


def case_report(
    *,
    case_id: str,
    passed: bool,
    metrics: dict,
    answer: str = "",
    retrieved: Sequence[str] | None = None,
    judge: dict | None = None,
    judge_expected: bool = False,
    error: str | None = None,
    latency_ms: float = 0.0,
) -> dict:
    """统一单条用例结果结构。judge_expected 表示该用例本应跑 judge（retrieval 类不用）。"""
    return {
        "id": case_id,
        "passed": passed,
        "metrics": metrics,
        "answer": answer[:500],
        "retrieved": list(retrieved or []),
        "judge": judge,  # None 表示 judge 失败降级，不计入均分
        "judge_expected": judge_expected,
        "error": error,
        "latency_ms": round(latency_ms, 2),
    }


def aggregate(cases: list[dict]) -> dict:
    """把单条用例结果聚合成 run 级 report。"""
    total = len(cases)
    if total == 0:
        return {"total": 0}
    passed = sum(1 for c in cases if c["passed"])
    errors = sum(1 for c in cases if c["error"])

    def _mean(values: list) -> float | None:
        vals = [v for v in values if isinstance(v, (int, float))]
        return round(sum(vals) / len(vals), 4) if vals else None

    def _is_number(v) -> bool:
        return isinstance(v, (int, float))

    metric_keys: set[str] = set()
    judge_keys: set[str] = set()
    for c in cases:
        metric_keys.update((c.get("metrics") or {}).keys())
        # judge 里可能混有 reasons 等非数值字段，只聚合数值维度
        judge_keys.update(k for k, v in (c.get("judge") or {}).items() if _is_number(v))

    # judge 成功率分母只算"本应跑 judge"的用例（retrieval 类不算）
    expected_cases = [c for c in cases if c.get("judge_expected")]
    judge_coverage = (
        round(sum(1 for c in expected_cases if c.get("judge")) / len(expected_cases), 4)
        if expected_cases else None
    )

    report = {
        "total": total,
        "passed": passed,
        "pass_rate": round(passed / total, 4),
        "errors": errors,
        "avg_latency_ms": _mean([c.get("latency_ms", 0.0) for c in cases]),
        "metrics": {k: _mean([(c.get("metrics") or {}).get(k) for c in cases]) for k in sorted(metric_keys)},
        "judge": {k: _mean([(c.get("judge") or {}).get(k) for c in cases]) for k in sorted(judge_keys)},
        "judge_coverage": judge_coverage,
    }
    return report
