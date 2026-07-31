"""Persy Unified Memory Graph models.

MemoryNode + TypedEdge 实现 Zep 双时序 + Mem0 更新策略 + Tana 类型继承。
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utc_now_iso() -> datetime:
    return datetime.now(UTC)


def _new_uuid() -> str:
    return str(uuid.uuid4())


class MemoryNodeType(str, enum.Enum):
    CONSTRAINT = "constraint"
    CONVENTION = "convention"
    LESSON = "lesson"
    EPISODIC = "episodic"
    PREFERENCE = "preference"
    ENTITY = "entity"
    DOC = "doc"
    ARTIFACT = "artifact"


class MemoryNodeStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    REJECTED = "rejected"
    DELETED = "deleted"
    ARCHIVED = "archived"
    SUPERSEDED = "superseded"


class EdgeType(str, enum.Enum):
    DERIVES_FROM = "derives_from"
    CONTRADICTS = "contradicts"
    SUPERSEDES = "supersedes"
    RELATES_TO = "relates_to"
    GROUNDED_IN = "grounded_in"
    EXTRACTED_FROM = "extracted_from"
    MIRRORS = "mirrors"


# 构造时应用的默认值（SQLAlchemy default= 仅在 flush 时触发，单测构造对象时为 None）
_NODE_CONSTRUCTION_DEFAULTS: dict[str, Any] = {
    "type": MemoryNodeType.DOC,
    "scope": "tenant",
    "scope_id": "",
    "status": MemoryNodeStatus.PENDING,
    "version": 1,
    "update_policy_on_conflict": "supersede",
    "update_policy_dedup_scope": "type+scope",
    "metadata_source": "manual",
    "metadata_source_policy": "needs_confirm",
    "metadata_tags": "",
    "metadata_recall_count": 0,
    "metadata_weight": 1.0,
    "metadata_decay_half_life_days": 90,
    "metadata_decay_min_weight": 0.1,
    "metadata_decay_boost_on_recall": 1.15,
    "metadata_confidence": 0.0,
    "metadata_chunk_count": 0,
    "content": "",
}

_EDGE_CONSTRUCTION_DEFAULTS: dict[str, Any] = {
    "type": EdgeType.RELATES_TO,
    "weight": 1.0,
    "context": "",
    "bidirectional": False,
}


class MemoryNode(Base):
    """统一记忆节点，承载 8 种类型的记忆。"""

    __tablename__ = "persy_memory_nodes"

    node_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_uuid)
    type: Mapped[MemoryNodeType] = mapped_column(default=MemoryNodeType.DOC)
    parent_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    title: Mapped[str] = mapped_column(String(160))
    content: Mapped[str] = mapped_column(Text, default="")
    scope: Mapped[str] = mapped_column(String(20), default="tenant")
    scope_id: Mapped[str] = mapped_column(String(160), default="")
    status: Mapped[MemoryNodeStatus] = mapped_column(default=MemoryNodeStatus.PENDING)
    version: Mapped[int] = mapped_column(Integer, default=1)
    previous_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Zep 双时序
    temporal_t_valid_start: Mapped[datetime] = mapped_column(default=_utc_now_iso)
    temporal_t_valid_end: Mapped[datetime | None] = mapped_column(nullable=True)
    temporal_t_created: Mapped[datetime] = mapped_column(default=_utc_now_iso)
    temporal_t_expired: Mapped[datetime | None] = mapped_column(nullable=True)

    # Mem0 更新策略
    update_policy_on_conflict: Mapped[str] = mapped_column(String(20), default="supersede")
    update_policy_dedup_scope: Mapped[str] = mapped_column(String(40), default="type+scope")

    # 元数据（拍平存储，避免 JSON 列兼容性问题）
    metadata_created_at: Mapped[datetime] = mapped_column(default=_utc_now_iso)
    metadata_updated_at: Mapped[datetime] = mapped_column(default=_utc_now_iso)
    metadata_last_recalled_at: Mapped[datetime | None] = mapped_column(nullable=True)
    metadata_recall_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_weight: Mapped[float] = mapped_column(Float, default=1.0)
    metadata_decay_half_life_days: Mapped[int] = mapped_column(Integer, default=90)
    metadata_decay_min_weight: Mapped[float] = mapped_column(Float, default=0.1)
    metadata_decay_boost_on_recall: Mapped[float] = mapped_column(Float, default=1.15)
    metadata_source: Mapped[str] = mapped_column(String(40), default="manual")
    metadata_source_policy: Mapped[str] = mapped_column(String(20), default="needs_confirm")
    metadata_tags: Mapped[str] = mapped_column(Text, default="")  # 逗号分隔
    metadata_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    metadata_chunk_count: Mapped[int] = mapped_column(Integer, default=0)

    outgoing_edges: Mapped[list[TypedEdge]] = relationship(
        foreign_keys="TypedEdge.source_node_id",
        back_populates="source_node",
        cascade="all, delete-orphan",
    )
    incoming_edges: Mapped[list[TypedEdge]] = relationship(
        foreign_keys="TypedEdge.target_node_id",
        back_populates="target_node",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_memory_nodes_scope", "scope", "scope_id"),
        Index("ix_memory_nodes_type_status", "type", "status"),
        Index("ix_memory_nodes_t_valid_end", "temporal_t_valid_end"),
    )

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # SQLAlchemy 的 mapped_column(default=...) 仅在 flush 时触发；
        # 这里在构造时补齐默认值，便于单测与离线对象使用。
        now = _utc_now_iso()
        if self.node_id is None:
            self.node_id = _new_uuid()
        if self.temporal_t_valid_start is None:
            self.temporal_t_valid_start = now
        if self.temporal_t_created is None:
            self.temporal_t_created = now
        if self.metadata_created_at is None:
            self.metadata_created_at = now
        if self.metadata_updated_at is None:
            self.metadata_updated_at = now
        for key, value in _NODE_CONSTRUCTION_DEFAULTS.items():
            if getattr(self, key) is None:
                setattr(self, key, value)

    def tags_list(self) -> list[str]:
        return [t.strip() for t in self.metadata_tags.split(",") if t.strip()]


class TypedEdge(Base):
    """类型化边，融入 Zep 双时序。"""

    __tablename__ = "persy_memory_edges"

    edge_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_uuid)
    source_node_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("persy_memory_nodes.node_id", ondelete="CASCADE")
    )
    target_node_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("persy_memory_nodes.node_id", ondelete="CASCADE")
    )
    type: Mapped[EdgeType] = mapped_column(default=EdgeType.RELATES_TO)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    context: Mapped[str] = mapped_column(Text, default="")
    bidirectional: Mapped[bool] = mapped_column(Boolean, default=False)

    # Zep 双时序
    temporal_t_valid_start: Mapped[datetime] = mapped_column(default=_utc_now_iso)
    temporal_t_valid_end: Mapped[datetime | None] = mapped_column(nullable=True)
    temporal_t_created: Mapped[datetime] = mapped_column(default=_utc_now_iso)

    source_node: Mapped[MemoryNode] = relationship(
        foreign_keys=[source_node_id], back_populates="outgoing_edges"
    )
    target_node: Mapped[MemoryNode] = relationship(
        foreign_keys=[target_node_id], back_populates="incoming_edges"
    )

    __table_args__ = (
        Index("ix_memory_edges_source", "source_node_id"),
        Index("ix_memory_edges_target", "target_node_id"),
        Index("ix_memory_edges_type", "type"),
    )

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if self.edge_id is None:
            self.edge_id = _new_uuid()
        now = _utc_now_iso()
        if self.temporal_t_valid_start is None:
            self.temporal_t_valid_start = now
        if self.temporal_t_created is None:
            self.temporal_t_created = now
        for key, value in _EDGE_CONSTRUCTION_DEFAULTS.items():
            if getattr(self, key) is None:
                setattr(self, key, value)
