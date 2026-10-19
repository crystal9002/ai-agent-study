"""轻量消息总线：所有 Agent 间通信的唯一通道。

为什么需要总线（而不是各处 print）：
  1. 可观察：每条消息落 history，事后可回放/写日志/tracing（呼应 04 教程）
  2. 可推送：订阅者（CLI 打印、SSE 队列、测试断言）拿到同一事件流
  3. 可审计：dispatch 谁派给谁、worker 交回什么，一目了然

消息协议（本教程约定）：
  Message(from, to, content, tool_events)
    from/to 是 Agent 名（"supervisor" / "researcher" / ...）
    content 是自然语言任务或结果
    tool_events 是 worker 执行过程中的工具调用明细（供可视化）
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Callable


@dataclass
class Message:
    from_: str          # 发送方 Agent 名（from 是 Python 关键字，加下划线）
    to: str             # 接收方："*" 表示广播
    content: str
    tool_events: list[dict] = field(default_factory=list)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["from"] = d.pop("from_")   # 对外字段用 from
        return d


class EventBus:
    """同步总线：emit 时立刻调用所有订阅者（简单可靠，无队列积压问题）。"""

    def __init__(self) -> None:
        self.history: list[Message] = []
        self._subscribers: list[Callable[[dict], None]] = []

    def subscribe(self, callback: Callable[[dict], None]) -> None:
        """订阅事件（dict 格式）。Web SSE 用它把事件塞进 queue。"""
        self._subscribers.append(callback)

    def emit(self, msg: Message) -> None:
        self.history.append(msg)
        event = msg.to_dict()
        for cb in self._subscribers:
            try:
                cb(event)
            except Exception:  # noqa: BLE001 —— 订阅者出错不能拖垮总线
                pass

    def send(self, from_: str, to: str, content: str, **kw) -> Message:
        """便捷方法：发一条消息并广播事件。"""
        msg = Message(from_=from_, to=to, content=content, **kw)
        self.emit(msg)
        return msg

    def transcript(self) -> str:
        """回放整个会话（调试用）。"""
        lines = []
        for m in self.history:
            arrow = f"{m.from_} → {m.to}"
            lines.append(f"[{arrow}] {m.content[:200]}")
        return "\n".join(lines)
