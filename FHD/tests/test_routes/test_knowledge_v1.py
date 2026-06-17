"""Tests for app.fastapi_routes.knowledge_v1 — using mock for unavailable RAG imports."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# Mock the missing RAG imports before importing the module
rag_mock = types.ModuleType("app.infrastructure.rag")
rag_mock.HybridRetriever = MagicMock
rag_mock.SemanticChunker = MagicMock
rag_mock.RetrievedChunk = MagicMock
rag_mock.get_default_embedder = MagicMock(return_value=None)
rag_mock.is_rag_enabled = MagicMock(return_value=False)
rag_mock.RagService = MagicMock
# Force override in case another test already loaded a partial mock
sys.modules["app.infrastructure.rag"] = rag_mock

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
    @patch("app.fastapi_routes.knowledge_v1._index")
    def test_successful_ingest(self, mock_index):
        mock_index.ingest.return_value = 3
        req = IngestRequest(text="Some text to ingest", source="test")
        result = ingest(req)
        assert result.success is True
        assert result.chunk_count == 3

    @patch("app.fastapi_routes.knowledge_v1._index")
    def test_ingest_error(self, mock_index):
        mock_index.ingest.side_effect = ValueError("bad input")
        req = IngestRequest(text="Some text", source="test")
        result = ingest(req)
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
        result = query(req)
        assert result.success is True
        assert len(result.chunks) == 1
        assert result.rag_enabled is True


class TestStatusEndpoint:
    @patch("app.fastapi_routes.knowledge_v1._index")
    @patch("app.fastapi_routes.knowledge_v1.is_rag_enabled", return_value=True)
    @patch("app.fastapi_routes.knowledge_v1.get_default_embedder", return_value=MagicMock())
    def test_status(self, mock_embedder, mock_rag, mock_index):
        mock_index.status.return_value = {"sources": 2, "chunks": 10}
        result = status()
        assert result.rag_enabled is True
        assert result.indexed_sources == 2
        assert result.indexed_chunks == 10


class TestHealthEndpoint:
    @patch("app.fastapi_routes.knowledge_v1._index")
    @patch("app.fastapi_routes.knowledge_v1.is_rag_enabled", return_value=False)
    @patch("app.fastapi_routes.knowledge_v1.get_default_embedder", return_value=None)
    def test_health(self, mock_embedder, mock_rag, mock_index):
        mock_index.status.return_value = {"sources": 0, "chunks": 0}
        result = health()
        assert result["success"] is True
        assert result["rag_enabled"] is False
