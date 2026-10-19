"""第一步：建知识库索引（离线批处理）。

用法：
    .venv/bin/python scripts/01_build_kb.py [文档目录，默认 data/]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from kba import kb


def main() -> None:
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent / "data"
    index_dir = Path(__file__).parent.parent / "index"
    print(f"扫描文档目录: {data_dir}")
    try:
        n = kb.build_index(data_dir, index_dir)
    except Exception as e:  # noqa: BLE001 —— 模型缺失/目录不存在都给出明确提示
        print(f"❌ 建库失败: {type(e).__name__}: {e}")
        return
    print(f"✅ 索引构建完成：{n} 个 chunk → {index_dir}")
    print("下一步: .venv/bin/python scripts/02_kb_agent.py \"团队版多少钱？\"")


if __name__ == "__main__":
    main()
