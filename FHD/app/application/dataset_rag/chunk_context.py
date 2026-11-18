"""分块上下文：章节标题提取与相邻块窗口扩展（small-to-big 检索）。"""

from __future__ import annotations

import re
from typing import Any

_HEADING = re.compile(r"(?m)^(#{1,6})[ \t]([^\n]*)")
_MAX_SECTION_CHARS = 200


def section_title(text: str, offset: int) -> str:
    """返回偏移位置之前最近的 Markdown 标题（没有则为空）。"""
    if not text:
        return ""
    end = max(0, min(len(text), int(offset) + 1))
    title = ""
    for match in _HEADING.finditer(text, 0, end):
        title = match.group(2).strip()
    return title[:_MAX_SECTION_CHARS]


def section_metadata(text: str, offset: int) -> dict[str, str]:
    title = section_title(text, offset)
    return {"section": title} if title else {}


def _leading_heading(text: str) -> str:
    """块开头就是 Markdown 标题时返回标题文字。"""
    match = _HEADING.match(str(text or "").lstrip())
    return match.group(2).strip()[:_MAX_SECTION_CHARS] if match else ""


def section_context(chunk: Any, siblings: list[Any], *, max_chars: int = 4000) -> str:
    """把命中块扩展到同一章节的完整正文（small-to-big）；不跨文档/版本/章节。"""
    metadata = getattr(chunk, "metadata", None) or {}
    text = str(getattr(chunk, "text", "") or "")
    title = str(metadata.get("section") or "") or _leading_heading(text)
    if not title:
        return text
    document_id = str(metadata.get("document_id") or "")
    version = metadata.get("document_version")
    siblings_scoped = sorted(
        (
            item
            for item in siblings
            if str((getattr(item, "metadata", None) or {}).get("document_id") or "") == document_id
            and (getattr(item, "metadata", None) or {}).get("document_version") == version
        ),
        key=lambda item: (item.char_start, item.chunk_index),
    )
    # 章节起点：优先找正文里带标题的那一块（它本身往往还没被写入 section 元数据），
    # 找不到再退回 section 相同的块。
    anchor = next(
        (
            index
            for index, item in enumerate(siblings_scoped)
            if _leading_heading(item.text) == title
        ),
        None,
    )
    if anchor is None:
        anchor = next(
            (
                index
                for index, item in enumerate(siblings_scoped)
                if str((getattr(item, "metadata", None) or {}).get("section") or "") == title
            ),
            None,
        )
    if anchor is None:
        return text
    scoped = [siblings_scoped[anchor]]
    for item in siblings_scoped[anchor + 1 :]:
        section = str((getattr(item, "metadata", None) or {}).get("section") or "")
        if section and section != title:
            break
        scoped.append(item)
    if len(scoped) <= 1:
        return text
    position = next((index for index, item in enumerate(scoped) if item is chunk), None)
    if position is None:
        position = next(
            (
                index
                for index, item in enumerate(scoped)
                if item.char_start == getattr(chunk, "char_start", None) and item.text == text
            ),
            0,
        )
    # 从命中块向两侧扩展，保证命中内容一定在预算内。
    budget = max(1, int(max_chars))
    parts: list[str] = [str(scoped[position].text or "")]
    used = len(parts[0])
    left, right = position - 1, position + 1
    while used < budget and (left >= 0 or right < len(scoped)):
        if left >= 0:
            candidate = str(scoped[left].text or "")
            if used + len(candidate) <= budget:
                parts.insert(0, candidate)
                used += len(candidate)
                left -= 1
            else:
                left = -1
        if right < len(scoped):
            candidate = str(scoped[right].text or "")
            if used + len(candidate) <= budget:
                parts.append(candidate)
                used += len(candidate)
                right += 1
            else:
                right = len(scoped)
    return "\n".join(part for part in parts if part)


def expanded_context(chunk: Any, siblings: list[Any], *, side_chars: int = 500) -> str:
    """把命中块与同文档相邻块拼成上下文窗口；不跨文档、不跨版本。"""
    metadata = getattr(chunk, "metadata", None) or {}
    document_id = str(metadata.get("document_id") or "")
    version = metadata.get("document_version")
    scoped = [
        item
        for item in siblings
        if str((getattr(item, "metadata", None) or {}).get("document_id") or "") == document_id
        and (getattr(item, "metadata", None) or {}).get("document_version") == version
    ]
    if not scoped:
        return str(getattr(chunk, "text", "") or "")
    ordered = sorted(scoped, key=lambda item: (item.char_start, item.chunk_index))

    def _key(item: Any) -> tuple[Any, Any, Any]:
        return (item.char_start, item.chunk_index, item.text[:32])

    position = next(
        (index for index, item in enumerate(ordered) if _key(item) == _key(chunk)),
        0,
    )
    parts: list[str] = []
    if position > 0:
        parts.append(ordered[position - 1].text[-side_chars:])
    parts.append(str(getattr(chunk, "text", "") or ""))
    if position + 1 < len(ordered):
        parts.append(ordered[position + 1].text[:side_chars])
    return "\n".join(part for part in parts if part)
