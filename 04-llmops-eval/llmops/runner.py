"""Golden set 评估运行器：RAG 用例与 Agent 用例，统一产出 cases + report。

- run_rag_case：检索命中指标（hit@k/precision@k/mrr）+ 等 containment + LLM judge
- run_agent_case：必调工具断言 + 成功断言（正则或包含串）+ 轮次约束
- 任一环节失败只标记该条 error，不中断全量
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from llmops import judge, metrics
from llmops.trace import Trace
from llmops import sut_agent, sut_rag

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def run_rag_case(case: dict, use_judge: bool = True, k: int = 3, trace: Trace | None = None,
                 sut=None) -> dict:
    """跑一条 RAG 用例并打分。sut 需实现 rag_query(question, k, trace=None)
    -> {"retrieved": [{"id","content",...}], "answer": str}，默认用内置 sut_rag。"""
    sut = sut or sut_rag
    qid, question = case["id"], case["question"]
    expected_chunks = case.get("expected_chunks", [])
    expected_contains = case.get("expected_answer_contains", [])
    case_type = case.get("type", "qa")
    t0 = time.perf_counter()
    try:
        if trace:
            with trace.span(f"case:{qid}"):
                with trace.span("rag_query", inputs=question):
                    out = sut.rag_query(question, k=k, trace=trace)
        else:
            out = sut.rag_query(question, k=k)
    except Exception as e:  # noqa: BLE001
        return metrics.case_report(
            case_id=qid, passed=False, metrics={}, error=f"{type(e).__name__}: {e}",
            latency_ms=(time.perf_counter() - t0) * 1000,
        )

    retrieved_texts = [c["content"] for c in out["retrieved"]]
    retrieved_ids = [c["id"] for c in out["retrieved"]]
    m = {
        f"hit@{k}": 1.0 if metrics.hit_at_k(retrieved_texts, expected_chunks, k) else 0.0,
        f"precision@{k}": metrics.precision_at_k(retrieved_texts, expected_chunks, k),
        "mrr": metrics.mrr(retrieved_texts, expected_chunks),
    }
    cont = metrics.containment(out["answer"], expected_contains)
    m["containment"] = 1.0 if cont else 0.0

    judge_result = None
    judge_expected = use_judge and case_type == "qa" and bool(out["answer"])
    if judge_expected:
        evidence = "\n".join(retrieved_texts)
        judge_result = judge.judge_both(
            question, out["answer"], evidence, trace=trace,
        )

    passed = cont and m[f"hit@{k}"] == 1.0
    return metrics.case_report(
        case_id=qid, passed=passed, metrics=m, answer=out["answer"],
        retrieved=retrieved_ids, judge=judge_result, judge_expected=judge_expected,
        latency_ms=(time.perf_counter() - t0) * 1000,
    )


def run_agent_case(case: dict, trace: Trace | None = None) -> dict:
    """跑一条 Agent 用例并断言成功条件。"""
    cid, goal = case["id"], case["goal"]
    must_tools = set(case.get("must_call_tools", []))
    success_regex = case.get("success_regex", "")
    expected_contains = case.get("expected_contains", [])
    max_turns = int(case.get("max_turns", 6))
    t0 = time.perf_counter()

    if trace:
        with trace.span(f"case:{cid}"):
            out = sut_agent.run_agent(goal, max_turns=max_turns, trace=trace)
    else:
        out = sut_agent.run_agent(goal, max_turns=max_turns)

    called = set(out["tool_calls"])
    tools_ok = must_tools.issubset(called) if must_tools else True
    if success_regex:
        answer_ok = metrics.regex_match(out["answer"], success_regex)
    else:
        answer_ok = metrics.containment(out["answer"], expected_contains)
    turns_ok = out["turns"] <= max_turns and not out["error"]

    m = {
        "tools_ok": 1.0 if tools_ok else 0.0,
        "answer_ok": 1.0 if answer_ok else 0.0,
        "turns": float(out["turns"]),
    }
    passed = tools_ok and answer_ok and turns_ok
    return metrics.case_report(
        case_id=cid, passed=passed, metrics=m, answer=out["answer"],
        retrieved=out["tool_calls"], error=out["error"],
        latency_ms=(time.perf_counter() - t0) * 1000,
    )


def run_rag_eval(cases: list[dict], use_judge: bool = True, k: int = 3,
                 name: str = "eval_rag", sut=None) -> dict:
    """全量跑 RAG golden set，返回可落盘的 run 记录。sut 同 run_rag_case。"""
    trace = Trace(name, meta={"model": __import__("os").getenv("LLM_MODEL", ""), "k": k, "judge": use_judge})
    results = []
    for i, case in enumerate(cases, 1):
        r = run_rag_case(case, use_judge=use_judge, k=k, trace=trace, sut=sut)
        results.append(r)
        mark = "✓" if r["passed"] else "✗"
        print(f"  [{i}/{len(cases)}] {mark} {r['id']}"
              + (f"  ⚠ {r['error']}" if r["error"] else "")
              + (f"  judge={r['judge']}" if r["judge"] else ""))
    report = metrics.aggregate(results)
    rec = trace.finish()
    rec["cases"] = results
    rec["report"] = report
    return rec


def run_agent_eval(cases: list[dict], name: str = "eval_agent") -> dict:
    """全量跑 Agent golden set。"""
    trace = Trace(name, meta={"model": __import__("os").getenv("LLM_MODEL", "")})
    results = []
    for i, case in enumerate(cases, 1):
        r = run_agent_case(case, trace=trace)
        results.append(r)
        mark = "✓" if r["passed"] else "✗"
        print(f"  [{i}/{len(cases)}] {mark} {r['id']}  tools={r['retrieved']}"
              + (f"  ⚠ {r['error']}" if r["error"] else ""))
    report = metrics.aggregate(results)
    rec = trace.finish()
    rec["cases"] = results
    rec["report"] = report
    return rec
