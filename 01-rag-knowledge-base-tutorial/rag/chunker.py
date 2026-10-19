"""文本分块：RAG 质量的第一道关卡。

分块目标：每个 chunk 是一个"语义完整、适合单独检索"的单元。
过大 → 检索不精准、噪声多；过小 → 丢失上下文、答案不完整。
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Chunk:
    doc_id: str      # 所属文档 ID
    chunk_id: str    # 全局唯一 ID，如 "doc1#0"
    text: str        # chunk 内容
    metadata: dict   # 来源、标题、序号等，供引用溯源


def _split_by_separator(text: str, seps: list[str]) -> list[str]:
    """按分隔符切分，分隔符本身不丢（保留结构信息）。"""
    parts = [text]
    for sep in seps:
        nxt: list[str] = []
        for p in parts:
            nxt.extend(p.split(sep))
        parts = nxt
    return [p for p in (s.strip() for s in parts) if p]


def _split_long(text: str, max_chars: int) -> list[str]:
    """超长片段按句子边界二次切分。"""
    if len(text) <= max_chars:
        return [text]
    sentences = re.split(r"(?<=[。！？!?.\n])", text)
    out, buf = [], ""
    for s in sentences:
        if len(buf) + len(s) > max_chars and buf:
            out.append(buf.strip())
            buf = ""
        buf += s
    if buf.strip():
        out.append(buf.strip())
    return out


def _pack(segments: list[str], chunk_size: int, overlap: int) -> list[str]:
    """把片段按 chunk_size 打包成块 + 重叠窗口（各策略共用的收尾逻辑）。"""
    chunks: list[str] = []
    buf = ""
    for seg in segments:
        if len(buf) + len(seg) <= chunk_size:
            buf = (buf + "\n" + seg) if buf else seg
        else:
            if buf:
                chunks.append(buf)
            if len(seg) > chunk_size:
                chunks.extend(_split_long(seg, chunk_size))
                buf = ""
            else:
                buf = seg
    if buf:
        chunks.append(buf)

    merged: list[str] = []
    for c in chunks:
        if merged and overlap > 0:
            c = merged[-1][-overlap:] + c
        merged.append(c)
    return merged


def _chunk_recursive(text: str, chunk_size: int, overlap: int, seps: list[str]) -> list[str]:
    """递归分块：段落 → 句子 → 硬切。通用默认，不依赖文档格式。"""
    return _pack(_split_by_separator(text, seps), chunk_size, overlap)


def _add_overlap(pieces: list[str], overlap: int) -> list[str]:
    """在成品块之间加重叠窗口。"""
    merged: list[str] = []
    for c in pieces:
        if merged and overlap > 0:
            c = merged[-1][-overlap:] + c
        merged.append(c)
    return merged


def _chunk_markdown(text: str, chunk_size: int, overlap: int) -> list[str]:
    """结构感知分块：按 # 标题切成"章节"，超长章节再用递归分块兜底。

    适用：Markdown 文档（本教程 data/ 即是）。chunk 自带标题上下文，
    metadata 可挂章节名，检索命中后引用更清晰。
    """
    lines = text.splitlines()
    sections: list[str] = []
    buf: list[str] = []

    def _has_content(buf_: list[str]) -> bool:
        # 只有标题行（连续多个 # 标题）不算正文，继续累积避免孤儿标题块
        return any(l.strip() and not re.match(r"^#{1,6}\s", l) for l in buf_)

    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m and _has_content(buf):
            sections.append("\n".join(buf).strip())
            buf = [line]
        else:
            buf.append(line)
    if buf:
        sections.append("\n".join(buf).strip())

    # 合并过短的章节（如只有标题没有正文），避免孤儿块
    min_chars = max(80, chunk_size // 6)
    pieces: list[str] = []
    for sec in (s for s in sections if s):
        if len(sec) < min_chars and pieces:
            pieces[-1] = pieces[-1] + "\n" + sec
        else:
            pieces.append(sec)

    # 超长章节内部再递归切分（overlap 在最后统一加）
    out: list[str] = []
    for sec in pieces:
        if len(sec) <= chunk_size:
            out.append(sec)
        else:
            out.extend(_pack(_split_by_separator(sec, ["\n\n", "\n", "。", ". "]),
                             chunk_size, overlap=0))
    return _add_overlap(out, overlap)


def _chunk_sentence(text: str, chunk_size: int, overlap: int) -> list[str]:
    """句子分块：不按段落打包，直接滑窗切句子序列。粒度最细。

    适用：FAQ 问答对、字幕、短文本密集的语料；chunk 小 → 检索精准但上下文少。
    """
    sentences = [s.strip() for s in re.split(r"(?<=[。！？!?.\n])", text) if s.strip()]
    return _pack(sentences, chunk_size, overlap)


STRATEGIES = {"recursive": _chunk_recursive, "markdown": _chunk_markdown, "sentence": _chunk_sentence}


def chunk_text(
    text: str,
    doc_id: str = "doc",
    chunk_size: int = 512,
    overlap: int = 64,
    seps: list[str] | None = None,
    strategy: str = "recursive",
) -> list[Chunk]:
    """按策略分块，带重叠窗口。

    Args:
        chunk_size: 每个 chunk 的目标字符数（中文场景 300~600 常用）
        overlap: 相邻 chunk 之间的重叠字符数，缓解边界截断
        seps: 递归策略的分隔符优先级，越靠前越优先切
        strategy: 分块方式，见 STRATEGIES：
            - recursive（默认）通用，段落/句子递归切分
            - markdown   结构感知，按标题切章节（Markdown 文档首选）
            - sentence   句子滑窗，粒度最细（FAQ/短文本语料）
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"未知分块策略: {strategy}，可选 {sorted(STRATEGIES)}")
    seps = seps or ["\n\n", "\n", "。", ". ", "；", "; "]

    if strategy == "recursive":
        pieces = _chunk_recursive(text, chunk_size, overlap, seps)
    else:
        pieces = STRATEGIES[strategy](text, chunk_size, overlap)

    return [
        Chunk(doc_id=doc_id, chunk_id=f"{doc_id}#{i}", text=c,
              metadata={"index": i, "strategy": strategy})
        for i, c in enumerate(pieces)
    ]
