"""分块上下文：章节标题提取与相邻块窗口扩展（small-to-big 检索）。"""

from __future__ import annotations

import re
from typing import Any

_HEADING = re.compile(r"(?m)^(#{1,6})\s+(.+?)\s*$")
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
