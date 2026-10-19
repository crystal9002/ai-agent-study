"""第二步：单次问答 —— 演示 检索 → 重排 → 生成 完整链路。

用法：
    python scripts/02_query.py "你的问题"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from rag import RAGPipeline
from rag.vector_store import DEFAULT_INDEX_DIR


def main() -> None:
    if len(sys.argv) < 2:
        print('用法: python scripts/02_query.py "你的问题"')
        return
    question = sys.argv[1]

    pipeline = RAGPipeline()
    pipeline.load_index(DEFAULT_INDEX_DIR)

    print("=" * 60)
    print(f"问题: {question}\n")

    chunks, scores = pipeline.retrieve(question)
    print("【检索结果（重排后）】")
    for i, (c, s) in enumerate(zip(chunks, scores), 1):
        preview = c.text[:60].replace("\n", " ")
        print(f"  [{i}] score={s:.4f}  {c.doc_id}  {preview}...")
    print("\n【生成回答】")

    result = pipeline.query(question)
    print(result.answer)


if __name__ == "__main__":
    main()
