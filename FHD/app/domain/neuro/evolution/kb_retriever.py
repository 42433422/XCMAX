"""知识库检索器（KBRetriever）——基于 LocalEmbedder 的本地 KB 检索。

检索 ``FHD/XCAGI/kb/patterns/`` 和 ``FHD/XCAGI/kb/fixes/`` 中的知识条目。

设计约束：
- 使用 ``LocalEmbedder``（Phase 3），无外部依赖。
- 启动时索引所有 KB 条目，支持增量添加。
- 余弦相似度检索，< 5ms（256 维向量点积极快）。
- best-effort：KB 不可用时返回空结果。

Phase 4 用途：为 ``RuntimeSelfFix`` 提供修复知识检索，为 ``ReflexPatternMiner`` 提供模式参考。
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.domain.neuro.subconscious.local_embedder import LocalEmbedder, get_local_embedder
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_KB_ROOT = Path(__file__).resolve().parents[4] / "XCAGI" / "kb"
_PATTERNS_DIR = _KB_ROOT / "patterns"
_FIXES_DIR = _KB_ROOT / "fixes"
_DEFAULT_TOP_K = 5


@dataclass
class KBEntry:
    """KB 条目。"""

    kind: str  # "pattern" | "fix"
    path: str
    content: str  # 用于检索的文本
    raw: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] = field(default_factory=list)


@dataclass
class KBSearchResult:
    """KB 检索结果。"""

    entry: KBEntry
    score: float  # 余弦相似度 0~1


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算余弦相似度。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _extract_search_text(raw: dict[str, Any]) -> str:
    """从 KB JSON 提取用于检索的文本。"""
    parts: list[str] = []
    for key in ("summary", "symptom", "root_cause", "before", "after", "pattern"):
        val = raw.get(key)
        if val and isinstance(val, str):
            parts.append(val)
    return " ".join(parts)


class KBRetriever:
    """知识库检索器。

    Args:
        embedder: 本地嵌入器（默认全局单例）。
        kb_root: KB 根目录（默认 ``FHD/XCAGI/kb``）。
    """

    def __init__(
        self,
        embedder: LocalEmbedder | None = None,
        kb_root: Path | None = None,
    ) -> None:
        self._embedder = embedder or get_local_embedder()
        self._kb_root = kb_root or _KB_ROOT
        self._entries: list[KBEntry] = []
        self._indexed = False

    def index(self) -> int:
        """索引 KB 目录中的所有条目。

        Returns:
            索引的条目数。
        """
        self._entries.clear()
        self._indexed = False

        patterns_dir = self._kb_root / "patterns"
        fixes_dir = self._kb_root / "fixes"

        count = 0
        count += self._index_dir(patterns_dir, "pattern")
        count += self._index_dir(fixes_dir, "fix")

        self._indexed = True
        logger.info("KBRetriever indexed %d entries", count)
        return count

    def _index_dir(self, dir_path: Path, kind: str) -> int:
        """索引单个目录。"""
        if not dir_path.exists():
            return 0

        count = 0
        for json_file in sorted(dir_path.glob("*.json")):
            try:
                raw = json.loads(json_file.read_text(encoding="utf-8"))
                content = _extract_search_text(raw)
                if not content:
                    continue
                embedding = self._embedder.embed_query(content)
                entry = KBEntry(
                    kind=kind,
                    path=str(json_file),
                    content=content,
                    raw=raw,
                    embedding=embedding,
                )
                self._entries.append(entry)
                count += 1
            except RECOVERABLE_ERRORS:
                logger.debug("Failed to index %s", json_file, exc_info=True)

        return count

    def add_entry(self, kind: str, raw: dict[str, Any], path: str = "") -> None:
        """增量添加一个 KB 条目。"""
        content = _extract_search_text(raw)
        if not content:
            return
        embedding = self._embedder.embed_query(content)
        self._entries.append(
            KBEntry(
                kind=kind,
                path=path,
                content=content,
                raw=raw,
                embedding=embedding,
            )
        )

    def search(
        self,
        query: str,
        *,
        kind: str | None = None,
        top_k: int = _DEFAULT_TOP_K,
    ) -> list[KBSearchResult]:
        """检索与查询最相关的 KB 条目。

        Args:
            query: 查询文本。
            kind: 限定条目类型（``"pattern"`` / ``"fix"`` / ``None`` 表示全部）。
            top_k: 返回的最大条目数。

        Returns:
            ``KBSearchResult`` 列表，按相似度降序。
        """
        if not self._indexed or not self._entries:
            return []

        query_vec = self._embedder.embed_query(query)
        if all(v == 0.0 for v in query_vec):
            return []

        scored: list[KBSearchResult] = []
        for entry in self._entries:
            if kind and entry.kind != kind:
                continue
            score = _cosine_similarity(query_vec, entry.embedding)
            scored.append(KBSearchResult(entry=entry, score=score))

        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:top_k]

    def search_patterns(self, query: str, top_k: int = _DEFAULT_TOP_K) -> list[KBSearchResult]:
        """检索模式条目。"""
        return self.search(query, kind="pattern", top_k=top_k)

    def search_fixes(self, query: str, top_k: int = _DEFAULT_TOP_K) -> list[KBSearchResult]:
        """检索修复条目。"""
        return self.search(query, kind="fix", top_k=top_k)

    @property
    def entry_count(self) -> int:
        """已索引的条目数。"""
        return len(self._entries)

    @property
    def is_indexed(self) -> bool:
        """是否已索引。"""
        return self._indexed

    def get_stats(self) -> dict[str, Any]:
        """获取统计。"""
        kind_counts: dict[str, int] = {}
        for entry in self._entries:
            kind_counts[entry.kind] = kind_counts.get(entry.kind, 0) + 1
        return {
            "total_entries": len(self._entries),
            "by_kind": kind_counts,
            "indexed": self._indexed,
            "kb_root": str(self._kb_root),
        }


_retriever: KBRetriever | None = None


def get_kb_retriever() -> KBRetriever:
    """获取全局 ``KBRetriever`` 单例。"""
    global _retriever
    if _retriever is None:
        _retriever = KBRetriever()
        try:
            _retriever.index()
        except RECOVERABLE_ERRORS:
            logger.debug("KBRetriever initial index failed", exc_info=True)
    return _retriever


def reset_kb_retriever() -> None:
    """重置单例（测试用）。"""
    global _retriever
    _retriever = None
