#!/usr/bin/env python3
"""跨教程闭环：用 04 的评估框架评估 03-knowledge-base-agent 的检索+生成。

03 的知识库（星云笔记语料，faiss+BM25+RRF）以 importlib 方式加载为 SUT，
评估数据是本教程 data/golden_kb.jsonl（10 条，覆盖定价/版本/限流/认证）。

依赖 03 教程的 venv（faiss-cpu / sentence-transformers / numpy 在那边）：
    cd 04-llmops-eval
    HF_HUB_OFFLINE=1 ../03-knowledge-base-agent/.venv/bin/python scripts/07_eval_kb.py --no-judge
    HF_HUB_OFFLINE=1 ../03-knowledge-base-agent/.venv/bin/python scripts/07_eval_kb.py
llmops（评估/LLM/judge）从本目录（04）加载，两边都在 sys.path 里，互不污染。
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

ROOT_04 = Path(__file__).resolve().parent.parent
ROOT_03 = ROOT_04.parent / "03-knowledge-base-agent"
sys.path.insert(0, str(ROOT_04))  # 让 03 的解释器也能 import llmops

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT_04 / ".env")  # DeepSeek key 从 04 的 .env 读，与其它 04 脚本同口径

# 离线加载 03 的知识库模块：KB 内部会拉 embedding 模型，先钉离线
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


def load_kba_kb():
    path = ROOT_03 / "kba" / "kb.py"
    if not path.exists():
        raise SystemExit(f"找不到 03 的知识库：{path}")
    spec = importlib.util.spec_from_file_location("kba_kb", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["kba_kb"] = mod  # dataclass 装饰器要求模块先注册进 sys.modules
    spec.loader.exec_module(mod)
    return mod


class KB_SUT:
    """把 03 的 kb.search 适配成 04 评估器要求的 rag_query 接口。"""

    SYSTEM = (
        "你是星云笔记的客服助手。只根据给定资料回答，不要编造；"
        "资料不足时明确说不知道。回答保持简洁。"
    )

    def __init__(self, kb_mod):
        self.kb = kb_mod

    def rag_query(self, question: str, k: int = 3, trace=None) -> dict:
        from llmops.llm import chat  # 延迟 import：LLM key 由 04 的 .env 提供

        hits = self.kb.search(question, k=k)
        retrieved = [
            {"id": f"{h['doc']}#{h['n']}", "content": h["text"],
             "source": h["doc"], "title": h["title"]}
            for h in hits
        ]
        context = "\n\n---\n\n".join(
            f"[{r['id']}] {r['title']}\n{r['content']}" for r in retrieved
        )
        messages = [
            {"role": "system", "content": self.SYSTEM},
            {"role": "user", "content": f"资料：\n{context}\n\n问题：{question}"},
        ]
        answer = chat(messages, temperature=0.0).content or ""
        return {"retrieved": retrieved, "answer": answer}


def main() -> None:
    ap = argparse.ArgumentParser(description="用 04 框架评估 03 的 KB")
    ap.add_argument("--no-judge", action="store_true", help="跳过 LLM-as-judge")
    ap.add_argument("--k", type=int, default=3)
    args = ap.parse_args()

    from llmops.runner import load_jsonl, run_rag_eval
    from llmops.store import save_run

    cases = load_jsonl(ROOT_04 / "data" / "golden_kb.jsonl")
    print(f"加载 03 知识库（{ROOT_03.name}）…")
    sut = KB_SUT(load_kba_kb())
    print(f"评估 {len(cases)} 条 golden_kb 用例（k={args.k}, judge={not args.no_judge}）")
    rec = run_rag_eval(cases, use_judge=not args.no_judge, k=args.k,
                       name="eval_kb_03", sut=sut)
    print()
    for m, v in rec["report"]["metrics"].items():
        print(f"  {m}: {v:.2%}" if isinstance(v, float) else f"  {m}: {v}")
    path = save_run("eval_kb", "eval_kb_03", rec)
    print(f"\n已保存: {path}")


if __name__ == "__main__":
    main()
