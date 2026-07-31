"""Memory Update Engine (借鉴 Mem0).

新记忆入库时的自动对账：ADD / UPDATE / DELETE / NOOP。
基于标题+内容的文本相似度判断（避免 LLM 依赖，可后续升级为向量+LLM）。
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from app.db.models.memory_graph import MemoryNode, MemoryNodeType
from app.infrastructure.memory_graph_store import MemoryGraphStore

UpdateAction = Literal["ADD", "UPDATE", "DELETE", "NOOP"]


@dataclass
class UpdateDecision:
    action: UpdateAction
    existing_node_id: str | None = None
    reason: str = ""


class MemoryUpdateEngine:
    """记忆更新引擎，对账新记忆和现有记忆的关系。"""

    def __init__(
        self,
        store: MemoryGraphStore,
        similarity_threshold: float = 0.85,
        duplicate_threshold: float = 0.92,
    ) -> None:
        self._store = store
        self._similarity_threshold = similarity_threshold
        self._duplicate_threshold = duplicate_threshold

    def evaluate(
        self,
        *,
        type: MemoryNodeType,
        title: str,
        content: str,
        scope: str,
        scope_id: str,
    ) -> UpdateDecision:
        candidates = self._store.list_active_nodes(
            scope=scope, scope_id=scope_id, node_type=type
        )
        if not candidates:
            return UpdateDecision(action="ADD", reason="无现有同类记忆")

        best_match = None
        best_score = 0.0
        for candidate in candidates:
            score = self._similarity(title, content, candidate)
            if score > best_score:
                best_score = score
                best_match = candidate

        if best_match is None:
            return UpdateDecision(action="ADD", reason="无相似记忆")

        if best_score >= self._duplicate_threshold:
            return UpdateDecision(
                action="NOOP",
                existing_node_id=best_match.node_id,
                reason=f"重复信息（相似度 {best_score:.2f}）",
            )

        if best_score >= self._similarity_threshold:
            return UpdateDecision(
                action="UPDATE",
                existing_node_id=best_match.node_id,
                reason=f"补充现有记忆（相似度 {best_score:.2f}）",
            )

        return UpdateDecision(action="ADD", reason=f"相似度低（{best_score:.2f}）")

    def _similarity(
        self, new_title: str, new_content: str, existing: MemoryNode
    ) -> float:
        title_sim = SequenceMatcher(None, new_title.lower(), existing.title.lower()).ratio()
        content_sim = SequenceMatcher(
            None, new_content.lower()[:500], (existing.content or "").lower()[:500]
        ).ratio()
        return max(title_sim, content_sim * 0.9)
