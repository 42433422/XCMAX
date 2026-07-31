"""Memory Graph Application Service.

业务编排层，整合 MemoryGraphStore + MemoryUpdateEngine。
"""

from __future__ import annotations

from typing import Any

from app.application.memory_update_engine import MemoryUpdateEngine
from app.db.models.memory_graph import MemoryNode, MemoryNodeType
from app.infrastructure.memory_graph_store import MemoryGraphStore


class MemoryGraphAppService:
    """记忆图谱应用服务。"""

    def __init__(
        self,
        store: MemoryGraphStore,
        update_engine: MemoryUpdateEngine,
    ) -> None:
        self._store = store
        self._update_engine = update_engine

    def ingest_engineering(
        self,
        *,
        type: MemoryNodeType,
        title: str,
        content: str,
        scope: str,
        scope_id: str,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        decision = self._update_engine.evaluate(
            type=type,
            title=title,
            content=content,
            scope=scope,
            scope_id=scope_id,
        )

        if decision.action == "NOOP":
            return {
                "success": True,
                "action": "NOOP",
                "node_id": decision.existing_node_id,
                "message": decision.reason,
            }

        node = self._store.create_node(
            type=type,
            title=title,
            content=content,
            scope=scope,
            scope_id=scope_id,
            source="trae",
            source_policy="auto_active",
            tags=tags,
        )

        if decision.action == "UPDATE" and decision.existing_node_id:
            self._store.supersede_node(
                decision.existing_node_id, node.node_id, context=decision.reason
            )

        return {
            "success": True,
            "action": decision.action,
            "node_id": node.node_id,
            "superseded_node_id": decision.existing_node_id,
            "message": decision.reason,
        }

    def get_active_constraints(
        self, *, scope: str, scope_id: str
    ) -> list[dict[str, Any]]:
        nodes = self._store.list_active_nodes(
            scope=scope, scope_id=scope_id, node_type=MemoryNodeType.CONSTRAINT
        )
        return [self._node_to_dict(n) for n in nodes]

    def get_active_conventions(
        self, *, scope: str, scope_id: str
    ) -> list[dict[str, Any]]:
        nodes = self._store.list_active_nodes(
            scope=scope, scope_id=scope_id, node_type=MemoryNodeType.CONVENTION
        )
        return [self._node_to_dict(n) for n in nodes]

    def search_memory(
        self,
        *,
        query: str,
        scope: str,
        scope_id: str,
        node_type: MemoryNodeType | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        # Phase 1: 简单关键词匹配（Phase 3 升级为 HybridRetriever 语义检索）
        nodes = self._store.list_active_nodes(
            scope=scope, scope_id=scope_id, node_type=node_type
        )
        query_lower = query.lower()
        scored: list[tuple[float, MemoryNode]] = []
        for node in nodes:
            title_match = query_lower in node.title.lower()
            content_match = query_lower in (node.content or "").lower()
            score = (1.0 if title_match else 0.0) + (0.5 if content_match else 0.0)
            if score > 0:
                scored.append((score * node.metadata_weight, node))
        scored.sort(key=lambda x: x[0], reverse=True)
        for _, node in scored[:top_k]:
            self._store.record_recall(node.node_id)
        return [self._node_to_dict(n) for _, n in scored[:top_k]]

    def _node_to_dict(self, node: MemoryNode) -> dict[str, Any]:
        return {
            "node_id": node.node_id,
            "type": node.type.value if hasattr(node.type, "value") else str(node.type),
            "title": node.title,
            "content": node.content,
            "scope": node.scope,
            "scope_id": node.scope_id,
            "status": node.status.value if hasattr(node.status, "value") else str(node.status),
            "weight": node.metadata_weight,
            "recall_count": node.metadata_recall_count,
            "tags": node.tags_list(),
            "t_valid_start": node.temporal_t_valid_start.isoformat()
            if node.temporal_t_valid_start
            else None,
            "t_valid_end": node.temporal_t_valid_end.isoformat()
            if node.temporal_t_valid_end
            else None,
        }
