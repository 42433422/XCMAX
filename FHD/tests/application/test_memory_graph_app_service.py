from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.infrastructure.memory_graph_store import MemoryGraphStore
from app.application.memory_update_engine import MemoryUpdateEngine
from app.application.memory_graph_app_service import MemoryGraphAppService
from app.db.models.memory_graph import MemoryNodeType


@pytest.fixture()
def service():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    store = MemoryGraphStore(Session(engine))
    update_engine = MemoryUpdateEngine(store)
    return MemoryGraphAppService(store=store, update_engine=update_engine)


def test_ingest_engineering_constraint(service):
    result = service.ingest_engineering(
        type=MemoryNodeType.CONSTRAINT,
        title="Ruff 唯一格式化工具",
        content="禁止 black/isort 与 Ruff 冲突",
        scope="project",
        scope_id="XCMAX",
        tags=["ruff", "format"],
    )
    assert result["success"] is True
    assert result["action"] == "ADD"
    assert result["node_id"]


def test_ingest_duplicate_returns_noop(service):
    service.ingest_engineering(
        type=MemoryNodeType.CONSTRAINT,
        title="Ruff 唯一格式化工具",
        content="禁止 black/isort",
        scope="project",
        scope_id="XCMAX",
    )
    result = service.ingest_engineering(
        type=MemoryNodeType.CONSTRAINT,
        title="Ruff 唯一格式化工具",
        content="禁止 black/isort",
        scope="project",
        scope_id="XCMAX",
    )
    assert result["action"] == "NOOP"


def test_search_active_nodes(service):
    service.ingest_engineering(
        type=MemoryNodeType.CONSTRAINT,
        title="Ruff 唯一格式化工具",
        content="禁止 black/isort",
        scope="project",
        scope_id="XCMAX",
    )
    service.ingest_engineering(
        type=MemoryNodeType.CONVENTION,
        title="备份脚本路径",
        content="FHD/scripts/backup/",
        scope="project",
        scope_id="XCMAX",
    )
    constraints = service.get_active_constraints(scope="project", scope_id="XCMAX")
    assert len(constraints) == 1
    assert constraints[0]["title"] == "Ruff 唯一格式化工具"
