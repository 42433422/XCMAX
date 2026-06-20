"""Tests for app.application.ai_chat_rag_integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.application.ai_chat_rag_integration import (
    augment_chat_with_rag,
    get_rag_service,
    get_rag_status,
)


class TestGetRagService:
    """Tests for get_rag_service."""

    @patch("app.application.ai_chat_rag_integration.is_rag_enabled", return_value=False)
    def test_returns_none_when_rag_disabled(self, mock_enabled: MagicMock) -> None:
        import app.application.ai_chat_rag_integration as mod

        mod._rag_service = None
        result = get_rag_service()
        assert result is None

    @patch("app.application.ai_chat_rag_integration.is_rag_enabled", return_value=True)
    @patch(
        "app.application.ai_chat_rag_integration.get_default_embedder",
        side_effect=ImportError("no embedder"),
    )
    def test_returns_none_on_init_failure(
        self, mock_embedder: MagicMock, mock_enabled: MagicMock
    ) -> None:
        import app.application.ai_chat_rag_integration as mod

        mod._rag_service = None
        result = get_rag_service()
        assert result is None


class TestAugmentChatWithRag:
    """Tests for augment_chat_with_rag."""

    @patch("app.application.ai_chat_rag_integration.get_rag_service", return_value=None)
    def test_fallback_when_rag_unavailable(self, mock_service: MagicMock) -> None:
        llm_call = MagicMock(return_value="LLM response")
        result = augment_chat_with_rag(
            user_message="hello",
            knowledge_text="some context",
            llm_call=llm_call,
        )
        assert result["answer"] == "LLM response"
        assert result["rag_enabled"] is False
        assert result["citations"] == []

    @patch("app.application.ai_chat_rag_integration.get_rag_service")
    def test_rag_success(self, mock_service: MagicMock) -> None:
        mock_rag = MagicMock()
        mock_rag.answer.return_value = {
            "answer": "RAG answer",
            "citations": [{"source": "doc1"}],
            "chunks": [{"text": "chunk1"}],
        }
        mock_service.return_value = mock_rag
        llm_call = MagicMock(return_value="unused")

        result = augment_chat_with_rag(
            user_message="hello",
            knowledge_text="context",
            llm_call=llm_call,
        )
        assert result["answer"] == "RAG answer"
        assert result["rag_enabled"] is True
        assert len(result["citations"]) == 1

    @patch("app.application.ai_chat_rag_integration.get_rag_service")
    def test_rag_failure_falls_back(self, mock_service: MagicMock) -> None:
        mock_rag = MagicMock()
        mock_rag.answer.side_effect = ValueError("RAG error")
        mock_service.return_value = mock_rag
        llm_call = MagicMock(return_value="fallback response")

        result = augment_chat_with_rag(
            user_message="hello",
            knowledge_text="context",
            llm_call=llm_call,
        )
        assert result["answer"] == "fallback response"
        assert result["rag_enabled"] is False
        assert "rag_error" in result


class TestGetRagStatus:
    """Tests for get_rag_status."""

    @patch("app.application.ai_chat_rag_integration.get_default_embedder", return_value=None)
    @patch("app.application.ai_chat_rag_integration.is_rag_enabled", return_value=False)
    def test_rag_disabled(self, mock_enabled: MagicMock, mock_embedder: MagicMock) -> None:
        result = get_rag_status()
        assert result["enabled"] is False
        assert result["service_available"] is False

    @patch("app.application.ai_chat_rag_integration.get_default_embedder", return_value=MagicMock())
    @patch("app.application.ai_chat_rag_integration.is_rag_enabled", return_value=True)
    @patch("app.application.ai_chat_rag_integration.get_rag_service", return_value=MagicMock())
    def test_rag_enabled(
        self, mock_service: MagicMock, mock_enabled: MagicMock, mock_embedder: MagicMock
    ) -> None:
        result = get_rag_status()
        assert result["enabled"] is True
        assert result["service_available"] is True
        assert result["embedder_available"] is True
