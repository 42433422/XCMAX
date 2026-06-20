"""Tests for app.fastapi_routes.knowledge_v1."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

# Mock the missing RAG classes before importing the module
_mock_rag = MagicMock()
_mock_rag.HybridRetriever = MagicMock
_mock_rag.SemanticChunker = MagicMock
_mock_rag.RetrievedChunk = MagicMock
_mock_rag.get_default_embedder = MagicMock(return_value=None)
_mock_rag.is_rag_enabled = MagicMock(return_value=False)

# Patch the rag module in sys.modules before import
_original_rag = sys.modules.get("app.infrastructure.rag")
sys.modules["app.infrastructure.rag"] = _mock_rag

try:
    from app.fastapi_routes.knowledge_v1 import (
        IngestRequest,
        QueryRequest,
        _KnowledgeIndex,
        health,
        ingest,
        query,
        router,
        status,
    )
finally:
    if _original_rag is not None:
        sys.modules["app.infrastructure.rag"] = _original_rag
    else:
        del sys.modules["app.infrastructure.rag"]


class TestIngestRequest:
    """Tests for IngestRequest model."""

    def test_default_values(self) -> None:
        req = IngestRequest(text="hello")
        assert req.text == "hello"
        assert req.source == "default"
        assert req.chunk_strategy == "semantic"
        assert req.chunk_size == 500
        assert req.chunk_overlap == 50

    def test_custom_values(self) -> None:
        req = IngestRequest(
            text="hello",
            source="test_source",
            chunk_strategy="fixed",
            chunk_size=1000,
            chunk_overlap=100,
        )
        assert req.source == "test_source"
        assert req.chunk_strategy == "fixed"
        assert req.chunk_size == 1000
        assert req.chunk_overlap == 100


class TestQueryRequest:
    """Tests for QueryRequest model."""

    def test_default_values(self) -> None:
        req = QueryRequest(query="test query")
        assert req.query == "test query"
        assert req.top_k == 5
        assert req.include_citations is True

    def test_custom_values(self) -> None:
        req = QueryRequest(query="test", top_k=10, include_citations=False)
        assert req.top_k == 10
        assert req.include_citations is False


class TestKnowledgeIndex:
    """Tests for _KnowledgeIndex."""

    @patch("app.fastapi_routes.knowledge_v1.get_default_embedder", return_value=None)
    @patch("app.fastapi_routes.knowledge_v1.SemanticChunker")
    @patch("app.fastapi_routes.knowledge_v1.HybridRetriever")
    def test_ingest_semantic_strategy(
        self, mock_retriever_cls: MagicMock, mock_chunker_cls: MagicMock, mock_embedder: MagicMock
    ) -> None:
        mock_chunker = MagicMock()
        chunk = MagicMock()
        chunk.text = "chunk text"
        chunk.char_start = 0
        chunk.char_end = 10
        chunk.strategy = "semantic"
        mock_chunker.split_by_semantic.return_value = [chunk]
        mock_chunker_cls.return_value = mock_chunker

        idx = _KnowledgeIndex()
        count = idx.ingest("some text", "source1", "semantic", 500, 50)
        assert count == 1
        mock_chunker.split_by_semantic.assert_called_once_with("some text")

    @patch("app.fastapi_routes.knowledge_v1.get_default_embedder", return_value=None)
    @patch("app.fastapi_routes.knowledge_v1.SemanticChunker")
    @patch("app.fastapi_routes.knowledge_v1.HybridRetriever")
    def test_ingest_fixed_strategy(
        self, mock_retriever_cls: MagicMock, mock_chunker_cls: MagicMock, mock_embedder: MagicMock
    ) -> None:
        mock_chunker = MagicMock()
        chunk = MagicMock()
        chunk.text = "fixed chunk"
        chunk.char_start = 0
        chunk.char_end = 11
        chunk.strategy = "fixed"
        mock_chunker.split_by_fixed.return_value = [chunk]
        mock_chunker_cls.return_value = mock_chunker

        idx = _KnowledgeIndex()
        count = idx.ingest("some text", "source1", "fixed", 200, 20)
        assert count == 1
        mock_chunker.split_by_fixed.assert_called_once_with(
            "some text", chunk_size=200, chunk_overlap=20
        )

    @patch("app.fastapi_routes.knowledge_v1.get_default_embedder", return_value=None)
    @patch("app.fastapi_routes.knowledge_v1.SemanticChunker")
    @patch("app.fastapi_routes.knowledge_v1.HybridRetriever")
    def test_status_empty(
        self, mock_retriever_cls: MagicMock, mock_chunker_cls: MagicMock, mock_embedder: MagicMock
    ) -> None:
        mock_chunker_cls.return_value = MagicMock()
        idx = _KnowledgeIndex()
        s = idx.status()
        assert s["sources"] == 0
        assert s["chunks"] == 0

    @patch("app.fastapi_routes.knowledge_v1.get_default_embedder", return_value=None)
    @patch("app.fastapi_routes.knowledge_v1.SemanticChunker")
    @patch("app.fastapi_routes.knowledge_v1.HybridRetriever")
    def test_query_triggers_rebuild(
        self, mock_retriever_cls: MagicMock, mock_chunker_cls: MagicMock, mock_embedder: MagicMock
    ) -> None:
        mock_chunker = MagicMock()
        mock_chunker_cls.return_value = mock_chunker
        mock_retriever = MagicMock()
        mock_retriever.retrieve.return_value = []
        mock_retriever_cls.return_value = mock_retriever

        idx = _KnowledgeIndex()
        idx._rebuild_needed = True
        idx.query("test", 5)
        mock_retriever.index.assert_called_once()


class TestIngestEndpoint:
    """Tests for ingest endpoint function."""

    @patch("app.fastapi_routes.knowledge_v1._index")
    def test_ingest_success(self, mock_index: MagicMock) -> None:
        mock_index.ingest.return_value = 3
        req = IngestRequest(text="hello world")
        result = ingest(req)
        assert result.success is True
        assert result.chunk_count == 3

    @patch("app.fastapi_routes.knowledge_v1._index")
    def test_ingest_value_error(self, mock_index: MagicMock) -> None:
        mock_index.ingest.side_effect = ValueError("bad input")
        req = IngestRequest(text="hello world")
        result = ingest(req)
        assert result.success is False
        assert "bad input" in result.message


class TestQueryEndpoint:
    """Tests for query endpoint function."""

    @patch("app.fastapi_routes.knowledge_v1._index")
    @patch("app.fastapi_routes.knowledge_v1.is_rag_enabled", return_value=True)
    def test_query_success(self, mock_rag: MagicMock, mock_index: MagicMock) -> None:
        mock_index.query.return_value = []
        req = QueryRequest(query="test")
        result = query(req)
        assert result.success is True
        assert result.rag_enabled is True


class TestStatusEndpoint:
    """Tests for status endpoint function."""

    @patch("app.fastapi_routes.knowledge_v1.get_default_embedder", return_value=None)
    @patch("app.fastapi_routes.knowledge_v1.is_rag_enabled", return_value=False)
    @patch("app.fastapi_routes.knowledge_v1._index")
    def test_status(
        self, mock_index: MagicMock, mock_rag: MagicMock, mock_embedder: MagicMock
    ) -> None:
        mock_index.status.return_value = {"sources": 2, "chunks": 10}
        result = status()
        assert result.rag_enabled is False
        assert result.indexed_sources == 2
        assert result.indexed_chunks == 10


class TestHealthEndpoint:
    """Tests for health endpoint function."""

    @patch("app.fastapi_routes.knowledge_v1.get_default_embedder", return_value=MagicMock())
    @patch("app.fastapi_routes.knowledge_v1.is_rag_enabled", return_value=True)
    @patch("app.fastapi_routes.knowledge_v1._index")
    def test_health(
        self, mock_index: MagicMock, mock_rag: MagicMock, mock_embedder: MagicMock
    ) -> None:
        mock_index.status.return_value = {"sources": 1, "chunks": 5}
        result = health()
        assert result["success"] is True
        assert result["rag_enabled"] is True
        assert result["embedder_available"] is True
