from __future__ import annotations

from datetime import datetime

from app.db.base import Base
from app.db.models.memory_graph import (
    EdgeType,
    MemoryNode,
    MemoryNodeStatus,
    MemoryNodeType,
    TypedEdge,
)


def test_memory_node_creation():
    node = MemoryNode(
        node_id="test-uuid-1",
        type=MemoryNodeType.CONSTRAINT,
        title="Ruff 是唯一格式化工具",
        content="禁止 black/isort 与 Ruff 冲突",
        scope="project",
        scope_id="XCMAX",
        status=MemoryNodeStatus.ACTIVE,
    )
    assert node.node_id == "test-uuid-1"
    assert node.type == MemoryNodeType.CONSTRAINT
    assert node.status == MemoryNodeStatus.ACTIVE
    assert node.temporal_t_valid_start is not None
    assert node.temporal_t_valid_end is None
    assert node.metadata_weight == 1.0
    assert node.metadata_recall_count == 0


def test_typed_edge_creation():
    edge = TypedEdge(
        edge_id="edge-uuid-1",
        source_node_id="node-a",
        target_node_id="node-b",
        type=EdgeType.SUPERSEDES,
        context="新约束替代旧约束",
    )
    assert edge.edge_id == "edge-uuid-1"
    assert edge.type == EdgeType.SUPERSEDES
    assert edge.bidirectional is False
    assert edge.temporal_t_valid_start is not None


def test_memory_node_status_enum():
    assert MemoryNodeStatus.ACTIVE.value == "active"
    assert MemoryNodeStatus.PENDING.value == "pending"
    assert MemoryNodeStatus.SUPERSEDED.value == "superseded"
    assert MemoryNodeStatus.ARCHIVED.value == "archived"
    assert MemoryNodeStatus.REJECTED.value == "rejected"
    assert MemoryNodeStatus.DELETED.value == "deleted"


def test_memory_node_type_enum():
    assert MemoryNodeType.CONSTRAINT.value == "constraint"
    assert MemoryNodeType.CONVENTION.value == "convention"
    assert MemoryNodeType.LESSON.value == "lesson"
    assert MemoryNodeType.EPISODIC.value == "episodic"
    assert MemoryNodeType.PREFERENCE.value == "preference"
    assert MemoryNodeType.ENTITY.value == "entity"
    assert MemoryNodeType.DOC.value == "doc"
    assert MemoryNodeType.ARTIFACT.value == "artifact"


def test_edge_type_enum():
    assert EdgeType.DERIVES_FROM.value == "derives_from"
    assert EdgeType.CONTRADICTS.value == "contradicts"
    assert EdgeType.SUPERSEDES.value == "supersedes"
    assert EdgeType.RELATES_TO.value == "relates_to"
    assert EdgeType.GROUNDED_IN.value == "grounded_in"
    assert EdgeType.EXTRACTED_FROM.value == "extracted_from"
    assert EdgeType.MIRRORS.value == "mirrors"
