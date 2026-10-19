"""01 · 追踪演示：给一条迷你 RAG 链打 Span 并落盘。

演示 llmops/trace.py 的核心能力：
    Trace + record_span 装饰器 + span 上下文 + token/成本归因 + JSONL 落盘。

跑一条问题走"检索 → 生成 → 两维裁判"，终端打印 span 树，
并保存到 runs/<run_id>.jsonl（供 05_web 仪表盘查看）。

用法：
    .venv/bin/python scripts/01_trace_demo.py
    .venv/bin/python scripts/01_trace_demo.py "团队版一年多少钱？"
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from llmops import judge
from llmops.store import save_run
from llmops.sut_rag import generate, retrieve
from llmops.trace import Trace


def main() -> None:
    question = sys.argv[1] if len(sys.argv) > 1 else "智能云盘团队版的价格是多少？"

    # ① 建 Trace：run_id 自动生成，meta 记录模型等环境信息
    tr = Trace("trace_demo", meta={"model": os.getenv("LLM_MODEL", ""), "question": question})

    # ② record_span 装饰器：自动记 latency / error / 父子关系
    @tr.record_span("retrieve")
    def retrieve_spanned(q: str, k: int = 3):
        return retrieve(q, k=k)

    # ③ with tr.span(...)：手动上下文，可分段记 output
    chunks = retrieve_spanned(question)
    chunk_ids = [c["id"] for c in chunks]

    with tr.span("generate", inputs=question) as sp:
        answer = generate(question, chunks, trace=tr)  # 内部 chat() 自动 add_usage 到本 span
        sp.output = answer

    # ④ LLM-as-judge 同样计入 trace（token 归因到 judge:* span）
    with tr.span("judge:faithfulness"):
        f = judge.faithfulness(question, answer, "\n".join(c["content"] for c in chunks), trace=tr)
    with tr.span("judge:relevance"):
        r = judge.relevance(question, answer, trace=tr)

    # ⑤ 打印 span 树报告
    print(tr.report_text())
    print(f"\n检索到: {chunk_ids}")
    print(f"答案: {answer}")
    print(f"faithfulness={f['score'] if f else '降级(null)'}  relevance={r['score'] if r else '降级(null)'}")

    # ⑥ 落盘 runs/<run_id>.jsonl，登记 index.jsonl
    record = tr.finish()
    record["report"] = {
        "question": question,
        "answer": answer[:500],
        "retrieved": chunk_ids,
        "judge": {"faithfulness": f, "relevance": r},
    }
    run_id = save_run("trace", "trace_demo", record)
    print(f"\n已保存 → runs/{run_id}.jsonl  （打开 Web 仪表盘可看 span 树）")


if __name__ == "__main__":
    main()
