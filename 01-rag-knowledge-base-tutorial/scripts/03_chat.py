"""第三步：交互式命令行聊天（流式输出 + 显示引用来源）。

用法：
    python scripts/03_chat.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from rag import RAGPipeline
from rag.vector_store import DEFAULT_INDEX_DIR


def main() -> None:
    pipeline = RAGPipeline()
    pipeline.load_index(DEFAULT_INDEX_DIR)
    print("RAG 知识库已就绪，输入问题开始对话（exit 退出）\n")

    while True:
        try:
            question = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question or question.lower() in ("exit", "quit", "q"):
            break

        answer_parts = []
        for kind, payload in pipeline.query_stream(question):
            if kind == "context":
                print("检索到: " + ", ".join(c.chunk_id for c in payload))
                print("AI> ", end="", flush=True)
            else:
                answer_parts.append(payload)
                print(payload, end="", flush=True)
        print("\n")

    print("再见")


if __name__ == "__main__":
    main()
