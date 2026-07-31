from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.application.memory_graph_app_service import MemoryGraphAppService
from app.application.memory_update_engine import MemoryUpdateEngine
from app.db.base import Base
from app.infrastructure.memory_graph_store import MemoryGraphStore
from scripts.dev.migrate_trae_memory_to_persy import TraeMemoryMigrator


@pytest.fixture()
def tmp_trae_memory(tmp_path):
    """模拟 ~/.trae-cn/memory/ 结构。"""
    project_dir = tmp_path / "projects" / "test-project"
    project_dir.mkdir(parents=True)
    (project_dir / "project_memory.md").write_text(
        """# Project Memory

## Hard Constraints
- Ruff 是唯一格式化工具，禁止 black/isort
- 覆盖率 floor 88% 行 / 81% 分支

## Engineering Conventions
- 备份脚本存储在 FHD/scripts/backup/

## Lessons Learned
- 文件级复制 SQLite 会损坏数据
""",
        encoding="utf-8",
    )
    (project_dir / "user_profile.md").write_text(
        """## User Preferences
- Communication language: Chinese
- Code style: minimal edits over full rewrites
""",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def app_service():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    store = MemoryGraphStore(Session(engine))
    return MemoryGraphAppService(store=store, update_engine=MemoryUpdateEngine(store))


def test_parse_project_memory(tmp_trae_memory):
    migrator = TraeMemoryMigrator(
        memory_root=tmp_trae_memory,
        scope="project",
        scope_id="XCMAX",
    )
    sections = migrator.parse_project_memory()
    assert "Hard Constraints" in sections
    assert "Engineering Conventions" in sections
    assert "Lessons Learned" in sections
    assert len(sections["Hard Constraints"]) == 2
    assert len(sections["Engineering Conventions"]) == 1
    assert len(sections["Lessons Learned"]) == 1


def test_migrate_project_memory(tmp_trae_memory, app_service):
    migrator = TraeMemoryMigrator(
        memory_root=tmp_trae_memory,
        scope="project",
        scope_id="XCMAX",
    )
    result = migrator.migrate(app_service)
    assert result["constraint"] == 2
    assert result["convention"] == 1
    assert result["lesson"] == 1
    constraints = app_service.get_active_constraints(scope="project", scope_id="XCMAX")
    assert len(constraints) == 2
    assert any("Ruff" in c["title"] for c in constraints)


def test_dry_run(tmp_trae_memory, app_service):
    migrator = TraeMemoryMigrator(
        memory_root=tmp_trae_memory,
        scope="project",
        scope_id="XCMAX",
    )
    result = migrator.migrate(app_service, dry_run=True)
    assert result["constraint"] == 2
    constraints = app_service.get_active_constraints(scope="project", scope_id="XCMAX")
    assert len(constraints) == 0  # dry-run 不实际写入
