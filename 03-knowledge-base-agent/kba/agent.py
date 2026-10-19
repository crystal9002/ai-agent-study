"""Agent 运行时：单循环 ReAct（检索 → 思考 → 工具 → 观察 → … → 带引用作答）。

与 02 教程 executor.py 的差异：
- 02 是 Plan-and-Execute 里的"单步执行器"，每步一个独立循环，靠外层编排；
- 本教程是**一个循环跑到底**的 ReAct：模型自己决定检索几次、要不要算账、
  何时写笔记、何时给结论——组合任务（查价 → 算账 → 写文件）在一个循环内完成。
"""
from __future__ import annotations

import json
from typing import Callable

from .llm import LLM
from .tools import ToolRegistry, register_default_tools

# 事件回调：Web 界面实时推送用（CLI 可传 None）
EventCB = Callable[[dict], None] | None

SYSTEM = """你是"星云笔记"企业知识库助手 Agent，可用工具：search_kb（检索知识库）、
calc（四则运算）、write_note（保存笔记到 output/）、list_notes（查看已有笔记）。

规则（必须遵守）：
1. 涉及产品功能、价格、接口、限额、流程等事实，**必须先调 search_kb 检索**，
   再基于检索结果作答；禁止凭记忆或常识编造知识库里没有的内容。
2. 引用检索结果时在句末标注来源编号，如 [1]、[2]，编号与 search_kb 返回的 n 一致，
   并在结论里给出简短的"来源"清单（编号 + title）。
3. search_kb 返回 results 为空时，明确回答"知识库中没有相关信息"，不要猜测。
4. 涉及金额、人数、折算时调用 calc 计算，不要心算关键数字。
5. 用户要求记录/保存结论时调用 write_note（Markdown 内容要完整可读）。
6. 信息齐了再给最终结论：中文、直接给答案、不要复述调用过程。"""


def _truncate(text: str, limit: int = 200) -> str:
    return text if len(text) <= limit else text[:limit] + "…(截断)"


class KBAgent:
    """知识库助手 Agent：一个 ReAct 循环跑到底，直到模型不再要求调工具。"""

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        llm: LLM | None = None,
        max_iters: int = 6,
    ):
        self.registry = registry or register_default_tools()
        self.llm = llm or LLM()
        self.max_iters = max_iters

    def run(self, question: str, on_event: EventCB = None) -> str:
        """跑一次问答，返回最终答案文本；过程通过 on_event 推送事件。"""
        def emit(ev: dict) -> None:
            if on_event:
                on_event(ev)

        messages: list[dict] = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": question},
        ]
        emit({"type": "start", "question": question,
              "tools": [t["function"]["name"] for t in self.registry.specs()]})

        for _ in range(self.max_iters):
            msg = self.llm.chat(messages, tools=self.registry.specs())
            messages.append(LLM.to_message(msg))

            # 模型不再要求调工具 → 给出最终结论，循环正常终止
            if not msg.tool_calls:
                answer = (msg.content or "").strip() or "（未返回内容）"
                emit({"type": "final", "content": answer})
                return answer

            # ① 执行工具 ② 结果以 tool 角色回填 → 进入下一轮思考
            for tc in msg.tool_calls:
                args = tc.function.arguments
                emit({"type": "tool_call", "name": tc.function.name, "args": args})
                result = self.registry.invoke(tc.function.name, args)
                emit({"type": "tool_result", "name": tc.function.name, "result": result})
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps(result, ensure_ascii=False)})

        # 兜底：超过轮数上限，如实告知而不是死循环（成本与失控的最后防线）
        answer = f"（执行中止：超过最大工具调用轮数 {self.max_iters}，请缩小问题范围重试）"
        emit({"type": "final", "content": answer})
        return answer
