"""COVERAGE_RAMP Phase 1 round 2: ai_chat_app_service deep paths (mocked LLM/workflow/deps)."""

from __future__ import annotations

import asyncio
import math
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.application.ai_chat_app_service import (
    AIChatApplicationService,
    get_ai_chat_app_service,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def chat_svc() -> AIChatApplicationService:
    return AIChatApplicationService()


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def test_get_ai_chat_app_service_singleton() -> None:
    assert get_ai_chat_app_service() is get_ai_chat_app_service()


# ---------------------------------------------------------------------------
# Static / class helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# process_chat main paths
# ---------------------------------------------------------------------------


@patch("app.services.get_conversation_service")
def test_persist_chat_turn_with_session(
    mock_conv: MagicMock, chat_svc: AIChatApplicationService
) -> None:
    mock_conv.return_value.save_turn = MagicMock(return_value=[1, 2])
    chat_svc._persist_chat_turn(
        "u1",
        "hello",
        {"session_id": "sess-1", "local_user_id": 17},
        {
            "success": True,
            "response": "world",
            "data": {"action": "followup", "data": {"intent": "chat"}},
        },
    )
    assert mock_conv.return_value.save_turn.call_count == 1


@patch("app.application.get_excel_vector_search_app_service")
def test_inject_excel_vector_context(
    mock_get: MagicMock, chat_svc: AIChatApplicationService
) -> None:
    mock_get.return_value.query.return_value = {
        "success": True,
        "hits": [{"text": "row1"}],
    }
    ctx = chat_svc._inject_excel_vector_context(
        "查报价",
        {"excel_index_id": "idx-1", "excel_top_k": 3},
    )
    assert ctx["excel_vector_context"]["index_id"] == "idx-1"


# ---------------------------------------------------------------------------
# _try_handle_dynamic_workflow (pro mode)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Tool execution branches
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Excel deterministic import shortcut (pro mode, high line ROI)
# ---------------------------------------------------------------------------
