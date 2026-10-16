"""第一步：加载文档 → 分块 → Embedding → 建 FAISS 索引（离线批处理）。

用法：
    python scripts/01_build_index.py [文档目录，默认 data/]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag import RAGPipeline

SUPPORTED = {".txt", ".md"}


def load_documents(root: Path) -> dict[str, str]:
    docs = {}
    for p in sorted(root.rglob("*")):
        if p.suffix.lower() in SUPPORTED and p.is_file():
            docs[p.stem] = p.read_text(encoding="utf-8")
            print(f"  加载 {p.relative_to(root)} ({len(docs[p.stem])} 字符)")
    return docs


def main() -> None:
    args = [a for a in sys.argv[1:]]
    strategy = None
    if "--strategy" in args:
        i = args.index("--strategy")
        strategy = args[i + 1]
        del args[i : i + 2]
    root = Path(args[0]) if args else Path(__file__).parent.parent / "data"
    print(f"扫描文档目录: {root}")
    docs = load_documents(root)
    if not docs:
        print("未找到 .txt/.md 文档，请先在 data/ 下放入文件")
        return

    pipeline = RAGPipeline(chunk_size=512, chunk_overlap=64, chunk_strategy=strategy)
    print(f"分块策略: {pipeline.chunk_strategy}（可用 --strategy recursive|markdown|sentence 切换）")
    pipeline.build_index(docs, index_dir=Path(__file__).parent.parent / "index")


if __name__ == "__main__":
    main()
