# mypy: disable-error-code="attr-defined"
"""Knowledge routes with real RAG imports and test-scoped service mocks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.fastapi_routes.knowledge_v1 import (
    IngestRequest,
    QueryRequest,
    _KnowledgeIndex,
    health,
    ingest,
    query,
    status,
)


class TestIngestRequest:
    def test_defaults(self):
        req = IngestRequest(text="hello")
        assert req.source == "default"
        assert req.chunk_strategy == "semantic"
        assert req.chunk_size == 500
        assert req.chunk_overlap == 50

    def test_custom_values(self):
        req = IngestRequest(
            text="hello",
            source="custom",
            chunk_strategy="fixed",
            chunk_size=1000,
            chunk_overlap=100,
        )
        assert req.source == "custom"
        assert req.chunk_strategy == "fixed"


class TestQueryRequest:
    def test_defaults(self):
        req = QueryRequest(query="test")
        assert req.top_k == 5
        assert req.include_citations is True

    def test_custom_values(self):
        req = QueryRequest(query="test", top_k=10, include_citations=False)
        assert req.top_k == 10
        assert req.include_citations is False


class TestKnowledgeIndex:
    def test_init(self):
        idx = _KnowledgeIndex()
        assert idx._chunks == []
        assert idx._sources == set()
        assert idx._rebuild_needed is True

    def test_status(self):
        idx = _KnowledgeIndex()
        s = idx.status()
        assert s["sources"] == 0
        assert s["chunks"] == 0


class TestIngestEndpoint:
    @patch(
        "app.fastapi_routes.knowledge_v1._mirror_ingest_to_persy",
        return_value={"success": True, "chunk_count": 3},
    )
    @patch("app.fastapi_routes.knowledge_v1._index")
    def test_successful_ingest(self, mock_index, _mock_mirror):
        mock_index.ingest.return_value = 3
        req = IngestRequest(text="Some text to ingest", source="test")
        result = ingest(req, request=MagicMock())
        assert result.success is True
        assert result.chunk_count == 3

    @patch(
        "app.fastapi_routes.knowledge_v1._mirror_ingest_to_persy", return_value={"success": False}
    )
    @patch("app.fastapi_routes.knowledge_v1._index")
    def test_ingest_error(self, mock_index, _mock_mirror):
        mock_index.ingest.side_effect = ValueError("bad input")
        req = IngestRequest(text="Some text", source="test")
        result = ingest(req, request=MagicMock())
        assert result.success is False
        assert result.chunk_count == 0


class TestQueryEndpoint:
    @patch("app.fastapi_routes.knowledge_v1._index")
    @patch("app.fastapi_routes.knowledge_v1.is_rag_enabled", return_value=True)
    def test_successful_query(self, mock_rag, mock_index):
        mock_chunk = MagicMock()
        mock_chunk.chunk_index = 0
        mock_chunk.text = "result"
        mock_chunk.score = 0.9
        mock_chunk.source = "test"
        mock_index.query.return_value = [mock_chunk]

        req = QueryRequest(query="test query")
        result = query(req, request=MagicMock())
        assert result.success is True
        assert len(result.chunks) == 1
        assert result.rag_enabled is True


class TestStatusEndpoint:
    @patch(
        "app.fastapi_routes.knowledge_v1._knowledge_runtime_snapshot",
        return_value={
            "rag_enabled": True,
            "embedder_available": True,
            "indexed_sources": 2,
            "indexed_chunks": 10,
            "dataset_count": 1,
            "dataset_document_count": 2,
            "dataset_chunk_count": 10,
            "semantic_embedding_available": True,
            "recommended_dataset_id": "persy-knowledge",
        },
    )
    def test_status(self, _snap):
        result = status(request=MagicMock())
        assert result.rag_enabled is True
        assert result.indexed_sources == 2
        assert result.indexed_chunks == 10


class TestHealthEndpoint:
    @patch(
        "app.fastapi_routes.knowledge_v1._knowledge_runtime_snapshot",
        return_value={
            "rag_enabled": False,
            "embedder_available": False,
            "indexed_sources": 0,
            "indexed_chunks": 0,
            "dataset_count": 0,
            "dataset_document_count": 0,
            "dataset_chunk_count": 0,
            "semantic_embedding_available": False,
            "recommended_dataset_id": "persy-knowledge",
        },
    )
    def test_health(self, _snap):
        result = health(request=MagicMock())
        assert result["success"] is True
        assert result["rag_enabled"] is False


class TestDatasetReadTenantScope:
    def test_admin_sees_all_tenants_inside_dataset(self):
        from app.application.dataset_rag_app_service import (
            DATASET_ADMIN_PERMISSION,
            DatasetAccessContext,
        )
        from app.fastapi_routes.knowledge_v1 import _dataset_read_tenant_scope

        admin = DatasetAccessContext(
            actor_id="admin",
            tenant_id="platform",
            permissions=frozenset({DATASET_ADMIN_PERMISSION}),
            is_admin=True,
        )
        assert _dataset_read_tenant_scope(admin) == ""

    def test_non_admin_stays_tenant_scoped(self):
        from app.application.dataset_rag_app_service import (
            DATASET_READ_PERMISSION,
            DatasetAccessContext,
        )
        from app.fastapi_routes.knowledge_v1 import _dataset_read_tenant_scope

        user = DatasetAccessContext(
            actor_id="u1",
            tenant_id="tenant-a",
            permissions=frozenset({DATASET_READ_PERMISSION}),
            is_admin=False,
        )
        assert _dataset_read_tenant_scope(user) == "tenant-a"
