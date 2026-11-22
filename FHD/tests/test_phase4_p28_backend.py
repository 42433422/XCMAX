"""COVERAGE_RAMP Phase 4 round 28:
session_account_meta enterprise CS gate, ai_chat process_chat workflow short-circuit."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.ai_chat_app_service import AIChatApplicationService
from app.application.session_account_meta import (
    is_session_market_admin,
)


def _chat_svc() -> AIChatApplicationService:
    return AIChatApplicationService()


# ---------------------------------------------------------------------------
# session_account_meta — enterprise dedicated CS
# ---------------------------------------------------------------------------


@patch("app.application.session_account_meta.load_session_account_meta")
def test_is_session_market_admin(mock_load: MagicMock) -> None:
    mock_load.return_value = {"account_kind": "admin", "market_is_admin": True}
    assert is_session_market_admin("sid") is True
    mock_load.return_value = {"account_kind": "admin", "market_is_admin": False}
    assert is_session_market_admin("sid") is False
    mock_load.return_value = None
    assert is_session_market_admin("sid") is False


# ---------------------------------------------------------------------------
# ai_chat — process_chat workflow short-circuit
# ---------------------------------------------------------------------------


@patch.object(AIChatApplicationService, "_persist_chat_turn")
@patch("app.application.agent_runtime.chat.run_runtime_chat")
def test_process_chat_returns_workflow_without_llm(
    mock_runtime: MagicMock, _mock_persist: MagicMock
) -> None:
    mock_runtime.return_value = {
        "success": True,
        "message": "处理完成",
        "response": "工作流结果",
        "data": {"text": "工作流结果", "action": "workflow_done", "data": {}},
    }
    svc = _chat_svc()
    out = svc.process_chat("u1", "导入数据库", source="pro", context={})
    assert out["success"] is True
    assert "工作流" in out["response"]
    mock_runtime.assert_called_once()
    assert not hasattr(svc, "workflow_planner")


@patch.object(AIChatApplicationService, "_persist_chat_turn")
def test_process_chat_empty_message(_mock_persist: MagicMock) -> None:
    svc = _chat_svc()
    out = svc.process_chat("u1", "")
    assert out["success"] is False
    assert "不能为空" in out["message"]
