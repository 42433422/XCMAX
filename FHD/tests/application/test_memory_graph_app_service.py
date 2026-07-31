from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.application.memory_graph_app_service import MemoryGraphAppService
from app.application.memory_update_engine import MemoryUpdateEngine
from app.db.base import Base
from app.db.models.memory_graph import MemoryNodeType
from app.infrastructure.memory_graph_store import MemoryGraphStore


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


# =============================================================================
# Phase 3 测试：HybridRetriever 集成
# =============================================================================


def test_search_memory_falls_back_to_keyword_when_rag_disabled(service):
    """RAG 关闭时应降级为关键词匹配。"""
    service.ingest_engineering(
        type=MemoryNodeType.CONSTRAINT,
        title="Ruff 唯一格式化工具",
        content="禁止 black/isort 与 Ruff 冲突",
        scope="project",
        scope_id="XCMAX",
    )
    with patch("app.application.memory_graph_app_service.is_rag_enabled", return_value=False):
        results = service.search_memory(query="ruff", scope="project", scope_id="XCMAX")
    assert len(results) == 1
    assert "Ruff" in results[0]["title"]


def test_search_memory_uses_semantic_when_rag_enabled(service):
    """RAG 启用 + embedder 可用时应用语义检索。"""
    service.ingest_engineering(
        type=MemoryNodeType.CONSTRAINT,
        title="Ruff 唯一格式化工具",
        content="禁止 black/isort 与 Ruff 冲突",
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

    # 构造一个简单的 embedder：对包含 "ruff" 的文本返回与 query 相同向量
    def fake_embedder(text: str) -> list[float]:
        text_lower = text.lower()
        if "ruff" in text_lower:
            return [1.0, 0.0]
        if "backup" in text_lower or "备份" in text_lower:
            return [0.0, 1.0]
        return [0.0, 0.0]

    with (
        patch("app.application.memory_graph_app_service.is_rag_enabled", return_value=True),
        patch(
            "app.application.memory_graph_app_service.get_default_embedder",
            return_value=fake_embedder,
        ),
    ):
        results = service.search_memory(query="ruff", scope="project", scope_id="XCMAX")

    # 语义检索应召回 Ruff 节点（标题或 content 含 ruff）
    assert len(results) >= 1
    assert any("Ruff" in r["title"] for r in results)
    # Ruff 节点应排在 backup 节点之前（cosine 相似度更高）
    assert results[0]["title"] == "Ruff 唯一格式化工具"


def test_search_memory_semantic_falls_back_when_embedder_none(service):
    """RAG 启用但 embedder 为 None 时降级为关键词匹配。"""
    service.ingest_engineering(
        type=MemoryNodeType.CONSTRAINT,
        title="Ruff 唯一格式化工具",
        content="禁止 black/isort",
        scope="project",
        scope_id="XCMAX",
    )
    with (
        patch("app.application.memory_graph_app_service.is_rag_enabled", return_value=True),
        patch(
            "app.application.memory_graph_app_service.get_default_embedder",
            return_value=None,
        ),
    ):
        results = service.search_memory(query="ruff", scope="project", scope_id="XCMAX")
    assert len(results) == 1
    assert "Ruff" in results[0]["title"]


def test_search_memory_semantic_falls_back_on_no_matches(service):
    """语义检索无命中（向量全为 0）时应降级为关键词匹配。"""
    service.ingest_engineering(
        type=MemoryNodeType.CONSTRAINT,
        title="Ruff 唯一格式化工具",
        content="禁止 black/isort",
        scope="project",
        scope_id="XCMAX",
    )

    def zero_embedder(text: str) -> list[float]:
        return [0.0, 0.0]

    with (
        patch("app.application.memory_graph_app_service.is_rag_enabled", return_value=True),
        patch(
            "app.application.memory_graph_app_service.get_default_embedder",
            return_value=zero_embedder,
        ),
    ):
        results = service.search_memory(query="ruff", scope="project", scope_id="XCMAX")
    # 语义无命中 → 关键词匹配兜底
    assert len(results) == 1
    assert "Ruff" in results[0]["title"]


def test_search_memory_semantic_records_recall(service):
    """语义检索命中后应记录召回（recall_count 增加）。"""
    service.ingest_engineering(
        type=MemoryNodeType.CONSTRAINT,
        title="Ruff 唯一格式化工具",
        content="禁止 black/isort",
        scope="project",
        scope_id="XCMAX",
    )
    node_id = service.get_active_constraints(scope="project", scope_id="XCMAX")[0]["node_id"]

    def fake_embedder(text: str) -> list[float]:
        return [1.0] if "ruff" in text.lower() else [0.0]

    with (
        patch("app.application.memory_graph_app_service.is_rag_enabled", return_value=True),
        patch(
            "app.application.memory_graph_app_service.get_default_embedder",
            return_value=fake_embedder,
        ),
    ):
        service.search_memory(query="ruff", scope="project", scope_id="XCMAX")

    refreshed = service._store.get_node(node_id)  # noqa: SLF001
    assert refreshed.metadata_recall_count >= 1
