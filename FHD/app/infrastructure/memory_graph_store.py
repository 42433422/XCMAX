"""Memory graph storage service.

封装 MemoryNode + TypedEdge 的 CRUD，复用 SQLAlchemy Session。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models.memory_graph import (
    EdgeType,
    MemoryNode,
    MemoryNodeStatus,
    MemoryNodeType,
    TypedEdge,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MemoryGraphStore:
    """记忆图谱存储服务。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_node(
        self,
        *,
        type: MemoryNodeType,
        title: str,
        content: str,
        scope: str,
        scope_id: str,
        parent_type: str | None = None,
        source: str = "manual",
        source_policy: str = "needs_confirm",
        tags: list[str] | None = None,
        confidence: float = 0.0,
    ) -> MemoryNode:
        status = (
            MemoryNodeStatus.ACTIVE
            if source_policy == "auto_active"
            else MemoryNodeStatus.PENDING
        )
        node = MemoryNode(
            type=type,
            parent_type=parent_type,
            title=title[:160],
            content=content,
            scope=scope,
            scope_id=scope_id,
            status=status,
            metadata_source=source,
            metadata_source_policy=source_policy,
            metadata_tags=",".join(tags or []),
            metadata_confidence=confidence,
        )
        self._session.add(node)
        self._session.commit()
        self._session.refresh(node)
        return node

    def get_node(self, node_id: str) -> MemoryNode | None:
        return self._session.get(MemoryNode, node_id)

    def list_active_nodes(
        self,
        *,
        scope: str,
        scope_id: str,
        node_type: MemoryNodeType | None = None,
        limit: int = 500,
    ) -> list[MemoryNode]:
        stmt = select(MemoryNode).where(
            MemoryNode.scope == scope,
            MemoryNode.scope_id == scope_id,
            MemoryNode.status == MemoryNodeStatus.ACTIVE,
            MemoryNode.temporal_t_valid_end.is_(None),
        )
        if node_type is not None:
            stmt = stmt.where(MemoryNode.type == node_type)
        stmt = stmt.limit(limit)
        return list(self._session.scalars(stmt))

    def supersede_node(
        self, old_node_id: str, new_node_id: str, context: str = ""
    ) -> TypedEdge | None:
        now = _utc_now()
        self._session.execute(
            update(MemoryNode)
            .where(MemoryNode.node_id == old_node_id)
            .values(
                status=MemoryNodeStatus.SUPERSEDED,
                temporal_t_valid_end=now,
                metadata_updated_at=now,
            )
        )
        edge = TypedEdge(
            source_node_id=new_node_id,
            target_node_id=old_node_id,
            type=EdgeType.SUPERSEDES,
            context=context,
            bidirectional=False,
        )
        self._session.add(edge)
        self._session.commit()
        self._session.refresh(edge)
        return edge

    def record_recall(self, node_id: str) -> None:
        node = self.get_node(node_id)
        if node is None:
            return
        now = _utc_now()
        new_weight = min(1.0, node.metadata_weight * node.metadata_decay_boost_on_recall)
        self._session.execute(
            update(MemoryNode)
            .where(MemoryNode.node_id == node_id)
            .values(
                metadata_recall_count=node.metadata_recall_count + 1,
                metadata_last_recalled_at=now,
                metadata_weight=new_weight,
                metadata_updated_at=now,
            )
        )
        self._session.commit()

    def add_edge(
        self,
        *,
        source_node_id: str,
        target_node_id: str,
        type: EdgeType,
        context: str = "",
        bidirectional: bool = False,
    ) -> TypedEdge:
        edge = TypedEdge(
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            type=type,
            context=context,
            bidirectional=bidirectional,
        )
        self._session.add(edge)
        self._session.commit()
        self._session.refresh(edge)
        return edge

    def list_backlinks(self, node_id: str) -> list[TypedEdge]:
        stmt = select(TypedEdge).where(
            TypedEdge.target_node_id == node_id,
            TypedEdge.temporal_t_valid_end.is_(None),
        )
        return list(self._session.scalars(stmt))
