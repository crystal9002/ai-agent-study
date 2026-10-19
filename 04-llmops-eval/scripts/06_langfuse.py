"""06 · Langfuse 对照：把本教程的原生 trace 接到生产观测平台。

对应 docs/06-production-platform.md。本脚本：
1. 读 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST；
2. 没配 → 打印接入指引，优雅退出（exit 0，不报错）；
3. 配了 → 跑一条带 span 的迷你 RAG 链，同款结构上报 Langfuse，
   在平台 UI 里可以看到与 01_trace_demo.py 完全对应的 trace 树。

先装框架依赖：
    .venv/bin/python -m pip install -r requirements-framework.txt

用法：
    .venv/bin/python scripts/06_langfuse.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

GUIDE = """
═══════ Langfuse 接入指引（优雅退出）═══════
Langfuse 是开源 LLM 观测平台（自托管或 cloud.langfuse.com），
对应关系：本教程 Trace ↔ Langfuse Trace，span ↔ Generation/Span，落盘 ↔ 平台上报。

1. 安装：.venv/bin/python -m pip install -r requirements-framework.txt
2. 注册 cloud.langfuse.com（或 docker 自托管），拿到项目 Keys
3. 写入 .env：
     LANGFUSE_PUBLIC_KEY=pk-lf-...
     LANGFUSE_SECRET_KEY=sk-lf-...
     LANGFUSE_HOST=https://cloud.langfuse.com   # 自托管改成你的地址
4. 再次运行：.venv/bin/python scripts/06_langfuse.py
5. 打开 Langfuse UI → Traces，即可看到与 01_trace_demo.py 同构的 trace 树，
   并有成本看板 / 检索质量 / 用户反馈闭环等生产功能。

本教程坚持"先原生手写讲透，再上平台"——结构对齐后，迁移只是换个 exporter。
"""


def main() -> None:
    pub = os.getenv("LANGFUSE_PUBLIC_KEY")
    sec = os.getenv("LANGFUSE_SECRET_KEY")
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    if not pub or not sec:
        print(GUIDE)
        return  # 未配置 → 指引 + 正常退出

    try:
        from langfuse import Langfuse  # noqa: PLC0415
    except ImportError:
        print("已配置 LANGFUSE_* 但未安装 SDK：")
        print("  .venv/bin/python -m pip install -r requirements-framework.txt")
        sys.exit(1)

    from llmops.sut_rag import generate, retrieve

    lf = Langfuse(public_key=pub, secret_key=sec, host=host)
    question = "智能云盘企业版支持单点登录吗？"

    # 与 01_trace_demo.py 同构：trace → span(retrieve/generate) → generation
    trace = lf.trace(name="langfuse_demo", input=question)
    chunks = retrieve(question, k=3)
    trace.span(name="retrieve", input={"query": question, "k": 3},
               output=[c["id"] for c in chunks])

    gen = trace.generation(name="generate", model=os.getenv("LLM_MODEL", "deepseek-chat"),
                           input=question)
    answer = generate(question, chunks)  # 注意：token 用量需在真实项目里手动 update(gen, usage=...)
    gen.end(output=answer)
    trace.update(output=answer)

    lf.flush()
    print("已上报 Langfuse：")
    print(f"  trace 输入: {question}")
    print(f"  答案: {answer[:120]}")
    print(f"  查看: {host.rstrip('/')}/project → Traces → langfuse_demo")


if __name__ == "__main__":
    main()
