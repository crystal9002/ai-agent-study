"""03-knowledge-base-agent 原生包：把 RAG 检索包成 Agent 工具。

    kb.py     精简 RAG：build_index(dir) / search(query, k)
    tools.py  工具注册表 + search_kb / calc / write_note / list_notes
    llm.py    OpenAI 兼容 Function Calling 封装
    agent.py  ReAct 循环（tool_calls 回填 + max_iters 兜底 + 引用约定）
"""
from . import kb
from .agent import KBAgent
from .llm import LLM
from .tools import register_default_tools

__all__ = ["kb", "KBAgent", "LLM", "register_default_tools"]
