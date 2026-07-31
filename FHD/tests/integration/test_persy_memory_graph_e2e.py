from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.infrastructure.memory_graph_store import MemoryGraphStore
from app.application.memory_update_engine import MemoryUpdateEngine
from app.application.memory_graph_app_service import MemoryGraphAppService
from scripts.dev.migrate_trae_memory_to_persy import TraeMemoryMigrator
from app.db.models.memory_graph import MemoryNodeType


@pytest.fixture()
def app_service():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    store = MemoryGraphStore(Session(engine))
    return MemoryGraphAppService(store=store, update_engine=MemoryUpdateEngine(store))


def test_full_migration_and_search(app_service, tmp_path):
    """端到端：迁移 Trae memory → 检索约束。"""
    project_dir = tmp_path / "projects" / "XCMAX"
    project_dir.mkdir(parents=True)
    (project_dir / "project_memory.md").write_text(
        """# Project Memory

## Hard Constraints
- Ruff 是唯一格式化工具：禁止 black/isort 与 Ruff 冲突
- 覆盖率 floor 88/81：2026-07-25 自 89/83 下调

## Engineering Conventions
- SSOT drift gate：真实入口是 ssot_cli.py gate

## Lessons Learned
- 文件级复制 SQLite 会损坏数据：必须用 backup API
""",
        encoding="utf-8",
    )

    migrator = TraeMemoryMigrator(
        memory_root=tmp_path, scope="project", scope_id="XCMAX"
    )
    result = migrator.migrate(app_service)
    assert result["constraint"] == 2
    assert result["convention"] == 1
    assert result["lesson"] == 1

    constraints = app_service.get_active_constraints(scope="project", scope_id="XCMAX")
    assert len(constraints) == 2
    titles = [c["title"] for c in constraints]
    assert any("Ruff" in t for t in titles)
    assert any("覆盖率" in t for t in titles)

    search_results = app_service.search_memory(
        query="Ruff", scope="project", scope_id="XCMAX"
    )
    assert len(search_results) >= 1
    assert "Ruff" in search_results[0]["title"]

    conventions = app_service.get_active_conventions(scope="project", scope_id="XCMAX")
    assert len(conventions) == 1
    assert "SSOT" in conventions[0]["title"]


def test_idempotent_migration(app_service, tmp_path):
    """迁移幂等性：重复迁移不产生重复节点。"""
    project_dir = tmp_path / "projects" / "XCMAX"
    project_dir.mkdir(parents=True)
    (project_dir / "project_memory.md").write_text(
        """# Project Memory

## Hard Constraints
- Ruff 唯一格式化工具：禁止 black/isort
""",
        encoding="utf-8",
    )

    migrator = TraeMemoryMigrator(
        memory_root=tmp_path, scope="project", scope_id="XCMAX"
    )
    migrator.migrate(app_service)
    migrator.migrate(app_service)  # 第二次迁移

    constraints = app_service.get_active_constraints(scope="project", scope_id="XCMAX")
    assert len(constraints) == 1  # 幂等，不重复
