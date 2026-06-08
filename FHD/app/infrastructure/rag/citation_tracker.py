"""引用溯源（Citation Tracking）。

解析 LLM 响应中的 `[1][2]` 标记，映射回 `RetrievedChunk`，输出 `citations` 字段。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from .hybrid_retriever import RetrievedChunk

logger = logging.getLogger(__name__)


@dataclass
class Citation:
    """单条引用。"""

    index: int
    text: str
    source: str
    chunk_index: int
    char_range: tuple[int, int]
    source_url: str = ""
    page: int | None = None


class CitationTracker:
    """
    把 LLM 响应中的 `[1][2]` 标记 → `Citation` 列表。

    用法：
      tracker = CitationTracker(retrieved_chunks=[...])
      response_text, citations = tracker.attach_citations(llm_output)
    """

    CITE_PATTERN = re.compile(r"\[(\d+)\]")

    def __init__(self, retrieved_chunks: list[RetrievedChunk]) -> None:
        self._chunks = retrieved_chunks

    def attach_citations(self, llm_output: str) -> tuple[str, list[Citation]]:
        """
        返回 (clean_text, citations)。
        clean_text 移除 [1][2] 标记；citations 列出每条被引用的 chunk。
        """
        if not llm_output:
            return llm_output or "", []

        cited_indexes = sorted({int(m.group(1)) for m in self.CITE_PATTERN.finditer(llm_output)})
        citations: list[Citation] = []
        for idx in cited_indexes:
            if 1 <= idx <= len(self._chunks):
                c = self._chunks[idx - 1]
                citations.append(
                    Citation(
                        index=idx,
                        text=c.text,
                        source=c.source,
                        chunk_index=c.chunk_index,
                        char_range=(c.char_start, c.char_end),
                        source_url=c.source_url,
                        page=c.page,
                    )
                )

        clean_text = self.CITE_PATTERN.sub("", llm_output).strip()
        return clean_text, citations

    def format_for_prompt(self) -> str:
        """给 LLM 注入引用索引提示。"""
        if not self._chunks:
            return ""
        lines = ["【参考资料】（请在回答中用 [1][2] 等标注来源）："]
        for i, c in enumerate(self._chunks, start=1):
            src = c.source_url or (f"chunk_{c.chunk_index}" if c.chunk_index else "source")
            page_info = f", 第{c.page}页" if c.page is not None else ""
            excerpt = c.text[:120].replace("\n", " ")
            lines.append(f"  [{i}] {src}{page_info}: {excerpt}")
        return "\n".join(lines)
