"""语义分块器（Semantic Chunker）。

将长文本按"句子边界 + 语义相似度断点"切分，替代固定窗口的暴力切分。
保留 fixed-window 作为 fallback（向后兼容）。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """分块结果。"""

    text: str
    chunk_index: int
    char_start: int
    char_end: int
    strategy: str = "semantic"
    metadata: dict[str, Any] | None = None


class SemanticChunker:
    """
    基于句子边界 + 语义相似度断点的分块器。

    算法：
      1) 切句（中英文标点）
      2) 计算相邻句的 embedding 余弦相似度
      3) 相似度 < threshold 处作为断点
      4) 合并句为 chunk；保留 char_range 元数据
    """

    DEFAULT_THRESHOLD = 0.5
    MIN_CHUNK_CHARS = 100
    MAX_CHUNK_CHARS = 1500

    def __init__(
        self,
        embedder: Callable[[str], list[float]] | None = None,
        threshold: float = DEFAULT_THRESHOLD,
        min_chunk_chars: int = MIN_CHUNK_CHARS,
        max_chunk_chars: int = MAX_CHUNK_CHARS,
    ) -> None:
        self._embedder = embedder
        self._threshold = threshold
        self._min_chunk_chars = min_chunk_chars
        self._max_chunk_chars = max_chunk_chars

    def split_by_semantic(self, text: str, threshold: float | None = None) -> list[Chunk]:
        """
        语义分块入口。
        若无 embedder 降级为 fixed。
        """
        if not text or not text.strip():
            return []
        if self._embedder is None:
            return self.split_by_fixed(text)

        thr = threshold if threshold is not None else self._threshold
        sentences = self._split_sentences(text)
        if len(sentences) < 2:
            return [
                Chunk(
                    text=text,
                    chunk_index=0,
                    char_start=0,
                    char_end=len(text),
                    strategy="semantic",
                )
            ]

        # 1) 计算相邻句相似度
        try:
            embeddings = [self._embedder(s["text"]) for s in sentences]
        except Exception as e:
            logger.warning("embedder 调用失败，降级 fixed: %s", e)
            return self.split_by_fixed(text)

        # 2) 找断点
        breakpoints: list[int] = [0]
        sentences[0]["char_start"]
        for i in range(1, len(sentences)):
            sim = self._cosine(embeddings[i - 1], embeddings[i])
            if sim < thr:
                breakpoints.append(sentences[i]["char_start"])
        breakpoints.append(len(text))

        # 3) 切分为 chunk
        chunks: list[Chunk] = []
        for i in range(len(breakpoints) - 1):
            a = breakpoints[i]
            b = breakpoints[i + 1]
            seg = text[a:b].strip()
            if not seg:
                continue
            chunks.append(
                Chunk(
                    text=seg,
                    chunk_index=len(chunks),
                    char_start=a,
                    char_end=b,
                    strategy="semantic",
                    metadata={"threshold": thr},
                )
            )

        # 4) 过小/过大 chunk 合并
        return self._merge_chunks(chunks, text)

    def split_by_fixed(
        self,
        text: str,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ) -> list[Chunk]:
        """固定窗口分块（fallback）。"""
        if not text or not text.strip():
            return []
        chunks: list[Chunk] = []
        i = 0
        idx = 0
        while i < len(text):
            j = min(i + chunk_size, len(text))
            seg = text[i:j]
            if seg.strip():
                chunks.append(
                    Chunk(
                        text=seg,
                        chunk_index=idx,
                        char_start=i,
                        char_end=j,
                        strategy="fixed",
                    )
                )
                idx += 1
            if j == len(text):
                break
            i = j - chunk_overlap
        return chunks

    @staticmethod
    def _split_sentences(text: str) -> list[dict[str, Any]]:
        """按中英文标点切句，保留 char_start。"""
        sentence_endings = re.compile(r"(?<=[。！？.!?])\s+|(?<=[。！？.!?])(?=[^\\s])")
        sentences: list[dict[str, Any]] = []
        cursor = 0
        for match in sentence_endings.finditer(text):
            end = match.end()
            sent = text[cursor:end].strip()
            if sent:
                sentences.append({"text": sent, "char_start": cursor})
            cursor = end
        if cursor < len(text):
            tail = text[cursor:].strip()
            if tail:
                sentences.append({"text": tail, "char_start": cursor})
        if not sentences:
            sentences.append({"text": text, "char_start": 0})
        return sentences

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    def _merge_chunks(self, chunks: list[Chunk], text: str) -> list[Chunk]:
        """过小合并 + 过大切分。"""
        merged: list[Chunk] = []
        buf_text = ""
        buf_start = 0
        for c in chunks:
            if not buf_text:
                buf_text = c.text
                buf_start = c.char_start
            else:
                buf_text = text[buf_start : c.char_end]
            if len(buf_text) >= self._min_chunk_chars and len(buf_text) <= self._max_chunk_chars:
                merged.append(
                    Chunk(
                        text=buf_text,
                        chunk_index=len(merged),
                        char_start=buf_start,
                        char_end=c.char_end,
                        strategy="semantic",
                    )
                )
                buf_text = ""
        if buf_text:
            merged.append(
                Chunk(
                    text=buf_text,
                    chunk_index=len(merged),
                    char_start=buf_start,
                    char_end=len(text),
                    strategy="semantic",
                )
            )
        return merged
