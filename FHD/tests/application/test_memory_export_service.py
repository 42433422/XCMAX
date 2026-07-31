"""Markdown 导出服务 MemoryExportService 的测试。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.application.memory_export_service import MemoryExportService
from app.db.base import Base
from app.db.models.memory_graph import EdgeType, MemoryNodeType
from app.infrastructure.memory_graph_store import MemoryGraphStore


@pytest.fixture()
def store() -> MemoryGraphStore:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return MemoryGraphStore(Session(engine))


@pytest.fixture()
def export_service(store: MemoryGraphStore) -> MemoryExportService:
    return MemoryExportService(store)


def test_export_node_returns_markdown_with_metadata(store: MemoryGraphStore, export_service):
    node = store.create_node(
        type=MemoryNodeType.CONSTRAINT,
        title="Ruff 唯一格式化工具",
        content="禁止 black/isort 与 Ruff 冲突",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
        tags=["ruff", "format"],
    )
    md = export_service.export_node(node.node_id)
    assert "### [active] Ruff 唯一格式化工具" in md
    assert f"- **node_id**: {node.node_id}" in md
    assert "- **type**: constraint" in md
    assert "- **status**: active" in md
    assert "- **weight**:" in md
    assert "- **content**: 禁止 black/isort 与 Ruff 冲突" in md
    assert "- **tags**: ruff, format" in md
    assert "- **backlinks**:" in md  # 即使空也应有该字段


def test_export_node_includes_backlinks(store: MemoryGraphStore, export_service):
    target = store.create_node(
        type=MemoryNodeType.CONVENTION,
        title="目标约定",
        content="被引用",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )
    source = store.create_node(
        type=MemoryNodeType.CONSTRAINT,
        title="来源约束",
        content="参见 [[目标约定]]",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )
    store.add_edge(
        source_node_id=source.node_id,
        target_node_id=target.node_id,
        type=EdgeType.RELATES_TO,
        bidirectional=True,
        context="wiki-link",
    )

    md = export_service.export_node(target.node_id)
    assert "- **backlinks**:" in md
    assert "来源约束" in md
    assert "relates_to" in md
    assert "[[目标约定]]" not in md  # backlinks 列出的是引用方标题，不是自身


def test_export_node_returns_placeholder_for_unknown_id(export_service):
    md = export_service.export_node("non-existent-id")
    assert "not found" in md.lower() or "不存在" in md


def test_export_scope_groups_by_type(store: MemoryGraphStore, export_service):
    store.create_node(
        type=MemoryNodeType.CONSTRAINT,
        title="约束 A",
        content="A",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )
    store.create_node(
        type=MemoryNodeType.CONSTRAINT,
        title="约束 B",
        content="B",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )
    store.create_node(
        type=MemoryNodeType.CONVENTION,
        title="约定 C",
        content="C",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )

    md = export_service.export_scope(scope="project", scope_id="XCMAX")
    assert "## constraint (2)" in md
    assert "## convention (1)" in md
    assert "### [active] 约束 A" in md
    assert "### [active] 约束 B" in md
    assert "### [active] 约定 C" in md


def test_export_scope_filters_by_node_type(store: MemoryGraphStore, export_service):
    store.create_node(
        type=MemoryNodeType.CONSTRAINT,
        title="约束 A",
        content="A",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )
    store.create_node(
        type=MemoryNodeType.CONVENTION,
        title="约定 C",
        content="C",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )

    md = export_service.export_scope(
        scope="project", scope_id="XCMAX", node_type=MemoryNodeType.CONVENTION
    )
    assert "## convention (1)" in md
    assert "约束 A" not in md
    assert "约定 C" in md


def test_export_scope_excludes_non_active_nodes(store: MemoryGraphStore, export_service):
    """pending / superseded 节点不应出现在 scope 导出中。"""
    store.create_node(
        type=MemoryNodeType.CONSTRAINT,
        title="Pending 约束",
        content="待确认",
        scope="project",
        scope_id="XCMAX",
        source_policy="needs_confirm",  # 触发 PENDING 状态
    )
    store.create_node(
        type=MemoryNodeType.CONSTRAINT,
        title="Active 约束",
        content="已生效",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )
    md = export_service.export_scope(scope="project", scope_id="XCMAX")
    assert "Active 约束" in md
    assert "Pending 约束" not in md


def test_export_scope_empty_scope_returns_header_only(export_service):
    md = export_service.export_scope(scope="project", scope_id="EMPTY")
    # 没有节点时也应返回有效 Markdown（可能含说明性文本）
    assert isinstance(md, str)
    assert "constraint" not in md.lower() or "(0)" in md
