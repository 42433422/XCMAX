from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.memory_graph import MemoryNode, MemoryNodeStatus, MemoryNodeType
from app.infrastructure.memory_graph_store import MemoryGraphStore


@pytest.fixture()
def store():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return MemoryGraphStore(Session(engine))


def test_create_node(store):
    node = store.create_node(
        type=MemoryNodeType.CONSTRAINT,
        title="Ruff 唯一格式化工具",
        content="禁止 black/isort",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )
    assert node.node_id
    assert node.status == MemoryNodeStatus.ACTIVE
    assert node.metadata_source_policy == "auto_active"


def test_get_node(store):
    created = store.create_node(
        type=MemoryNodeType.LESSON,
        title="test lesson",
        content="lesson content",
        scope="project",
        scope_id="XCMAX",
    )
    fetched = store.get_node(created.node_id)
    assert fetched is not None
    assert fetched.title == "test lesson"


def test_list_active_constraints(store):
    store.create_node(
        type=MemoryNodeType.CONSTRAINT,
        title="constraint 1",
        content="c1",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )
    store.create_node(
        type=MemoryNodeType.CONVENTION,
        title="convention 1",
        content="v1",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )
    constraints = store.list_active_nodes(
        scope="project", scope_id="XCMAX", node_type=MemoryNodeType.CONSTRAINT
    )
    assert len(constraints) == 1
    assert constraints[0].title == "constraint 1"


def test_supersede_node(store):
    old = store.create_node(
        type=MemoryNodeType.CONSTRAINT,
        title="old constraint",
        content="old",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )
    new = store.create_node(
        type=MemoryNodeType.CONSTRAINT,
        title="new constraint",
        content="new",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )
    store.supersede_node(old.node_id, new.node_id, context="版本更新")
    from app.db.models.memory_graph import MemoryNodeStatus

    refreshed_old = store.get_node(old.node_id)
    assert refreshed_old.status == MemoryNodeStatus.SUPERSEDED
    assert refreshed_old.temporal_t_valid_end is not None


def test_record_recall(store):
    node = store.create_node(
        type=MemoryNodeType.CONSTRAINT,
        title="test",
        content="content",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )
    store.record_recall(node.node_id)
    refreshed = store.get_node(node.node_id)
    assert refreshed.metadata_recall_count == 1
    assert refreshed.metadata_last_recalled_at is not None
