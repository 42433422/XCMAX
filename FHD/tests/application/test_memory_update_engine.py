from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.memory_graph import MemoryNodeStatus, MemoryNodeType
from app.infrastructure.memory_graph_store import MemoryGraphStore
from app.application.memory_update_engine import MemoryUpdateEngine, UpdateDecision


@pytest.fixture()
def engine_and_store():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    store = MemoryGraphStore(Session(engine))
    return engine, store


def store_fixture_with_engine(engine_and_store):
    return engine_and_store[0], engine_and_store[1]


def test_add_new_memory(engine_and_store):
    _, store = store_fixture_with_engine(engine_and_store)
    engine = MemoryUpdateEngine(store, similarity_threshold=0.85)
    decision = engine.evaluate(
        type=MemoryNodeType.CONSTRAINT,
        title="Ruff 唯一格式化工具",
        content="禁止 black/isort",
        scope="project",
        scope_id="XCMAX",
    )
    assert decision.action == "ADD"
    assert decision.existing_node_id is None


def test_noop_duplicate(engine_and_store):
    _, store = store_fixture_with_engine(engine_and_store)
    engine = MemoryUpdateEngine(store, similarity_threshold=0.85)
    store.create_node(
        type=MemoryNodeType.CONSTRAINT,
        title="Ruff 唯一格式化工具",
        content="禁止 black/isort",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )
    decision = engine.evaluate(
        type=MemoryNodeType.CONSTRAINT,
        title="Ruff 唯一格式化工具",
        content="禁止 black/isort",
        scope="project",
        scope_id="XCMAX",
    )
    assert decision.action == "NOOP"
    assert decision.existing_node_id is not None


def test_update_supersede(engine_and_store):
    _, store = store_fixture_with_engine(engine_and_store)
    engine = MemoryUpdateEngine(store, similarity_threshold=0.85)
    store.create_node(
        type=MemoryNodeType.CONSTRAINT,
        title="覆盖率 floor 89/83",
        content="后端覆盖率 floor 89/83",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )
    decision = engine.evaluate(
        type=MemoryNodeType.CONSTRAINT,
        title="覆盖率 floor 88/81",
        content="后端覆盖率 floor 88/81（2026-07-25 下调）",
        scope="project",
        scope_id="XCMAX",
    )
    assert decision.action in ("UPDATE", "ADD")
