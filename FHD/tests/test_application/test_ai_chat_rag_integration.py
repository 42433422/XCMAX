"""Tests for app.application.ai_chat_rag_integration — with RAG module mocked."""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# Mock the RAG module before importing
rag_mock = types.ModuleType("app.infrastructure.rag")
rag_mock.RagService = MagicMock
rag_mock.get_default_embedder = MagicMock(return_value=None)
rag_mock.is_rag_enabled = MagicMock(return_value=False)
rag_mock.HybridRetriever = MagicMock
rag_mock.SemanticChunker = MagicMock
rag_mock.RetrievedChunk = MagicMock
# Override the existing module if already loaded
_original_rag = sys.modules.get("app.infrastructure.rag")
sys.modules["app.infrastructure.rag"] = rag_mock

try:
    from app.application.ai_chat_rag_integration import (
        augment_chat_with_rag,
        get_rag_service,
        get_rag_status,
    )
finally:
    if _original_rag is not None:
        sys.modules["app.infrastructure.rag"] = _original_rag
    else:
        del sys.modules["app.infrastructure.rag"]


class TestGetRagService:
    @patch("app.application.ai_chat_rag_integration.is_rag_enabled", return_value=False)
    def test_rag_disabled_returns_none(self, mock_enabled):
        import app.application.ai_chat_rag_integration as mod
        mod._rag_service = None
        result = get_rag_service()
        assert result is None

    @patch("app.application.ai_chat_rag_integration.is_rag_enabled", return_value=True)
    @patch("app.application.ai_chat_rag_integration.get_default_embedder", return_value=None)
    @patch("app.application.ai_chat_rag_integration.RagService", side_effect=RuntimeError("no rag"))
    def test_rag_init_failure_returns_none(self, mock_rag, mock_embedder, mock_enabled):
        import app.application.ai_chat_rag_integration as mod
        mod._rag_service = None
        result = get_rag_service()
        assert result is None


class TestAugmentChatWithRag:
    @patch("app.application.ai_chat_rag_integration.get_rag_service", return_value=None)
    def test_rag_disabled_falls_back_to_llm(self, mock_rag):
        llm_call = MagicMock(return_value="LLM response")
        result = augment_chat_with_rag(
            user_message="hello",
            knowledge_text="",
            llm_call=llm_call,
        )
        assert result["answer"] == "LLM response"
        assert result["rag_enabled"] is False
        assert result["citations"] == []

    @patch("app.application.ai_chat_rag_integration.get_rag_service")
    def test_rag_enabled_returns_result(self, mock_rag):
        mock_service = MagicMock()
        mock_service.answer.return_value = {
            "answer": "RAG answer",
            "citations": [{"text": "ref"}],
            "chunks": [],
        }
        mock_rag.return_value = mock_service

        llm_call = MagicMock(return_value="fallback")
        result = augment_chat_with_rag(
            user_message="hello",
            knowledge_text="context",
            llm_call=llm_call,
        )
        assert result["answer"] == "RAG answer"
        assert result["rag_enabled"] is True

    @patch("app.application.ai_chat_rag_integration.get_rag_service")
    def test_rag_exception_falls_back(self, mock_rag):
        mock_service = MagicMock()
        mock_service.answer.side_effect = ValueError("RAG error")
        mock_rag.return_value = mock_service

        llm_call = MagicMock(return_value="fallback response")
        result = augment_chat_with_rag(
            user_message="hello",
            knowledge_text="context",
            llm_call=llm_call,
        )
        assert result["rag_enabled"] is False
        assert "rag_error" in result


class TestGetRagStatus:
    @patch("app.application.ai_chat_rag_integration.is_rag_enabled", return_value=False)
    @patch("app.application.ai_chat_rag_integration.get_default_embedder", return_value=None)
    def test_rag_disabled(self, mock_embedder, mock_enabled):
        result = get_rag_status()
        assert result["enabled"] is False
        assert result["service_available"] is False

    @patch("app.application.ai_chat_rag_integration.is_rag_enabled", return_value=True)
    @patch("app.application.ai_chat_rag_integration.get_rag_service", return_value=MagicMock())
    @patch("app.application.ai_chat_rag_integration.get_default_embedder", return_value=MagicMock())
    def test_rag_enabled(self, mock_embedder, mock_rag, mock_enabled):
        result = get_rag_status()
        assert result["enabled"] is True
        assert result["service_available"] is True
        assert result["embedder_available"] is True
