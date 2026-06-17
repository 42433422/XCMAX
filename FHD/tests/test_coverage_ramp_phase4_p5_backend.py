"""COVERAGE_RAMP Phase 4 round 5: ai_chat process_chat edges, tools legacy sweep."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.application.ai_chat_app_service import AIChatApplicationService
from app.services.tools_payload_legacy import dispatch_legacy_tool_payload


def _j(data, status=200):
    return {"body": data, "status": status}


def _hdr(k, default=""):
    return default


def _dispatch(tool_id, action, params=None):
    return dispatch_legacy_tool_payload(
        tool_id,
        action,
        params or {},
        json_response_fn=_j,
        hdr_getter=_hdr,
        parse_order_text_fn=lambda t: {},
    )


def _chat_svc() -> AIChatApplicationService:
    mock_ai = MagicMock()

    async def _chat(*args, **kwargs):
        return {"success": True, "text": "好的", "action": "followup", "data": {}}

    mock_ai.chat = _chat
    with (
        patch(
            "app.application.ai_chat_app_service.get_ai_conversation_service", return_value=mock_ai
        ),
        patch("app.application.ai_chat_app_service.LLMWorkflowPlanner"),
        patch("app.application.ai_chat_app_service.HybridRiskGate"),
        patch("app.application.ai_chat_app_service.WorkflowEngine"),
        patch("app.application.ai_chat_app_service.get_approval_service"),
    ):
        svc = AIChatApplicationService()
        svc.ai_service = mock_ai
        return svc


def test_process_chat_empty_message() -> None:
    svc = _chat_svc()
    out = svc.process_chat("u1", "")
    assert out["success"] is False


def test_process_chat_basic_success() -> None:
    svc = _chat_svc()
    with patch.object(svc, "_persist_chat_turn"):
        out = svc.process_chat("u1", "你好", source="basic")
    assert out["success"] is True


def test_process_chat_recoverable_error() -> None:
    svc = _chat_svc()

    async def _fail(*a, **k):
        raise RuntimeError("service down")

    svc.ai_service.chat = _fail
    out = svc.process_chat("u1", "查库存")
    assert out["success"] is False


def test_handle_confirmation_flow_noop() -> None:
    svc = _chat_svc()
    svc._handle_confirmation_flow("u1", "普通消息", None)


@patch("app.services.get_printer_service")
def test_legacy_print_test_action(mock_get: MagicMock) -> None:
    mock_get.return_value.test_printer.return_value = {"success": True}
    resp = _dispatch("print", "test", {"printer_name": "HP"})
    assert resp["body"]["success"] is True


@patch("app.services.get_database_service")
def test_legacy_database_list_backups(mock_get: MagicMock) -> None:
    mock_get.return_value.list_backups.return_value = {"success": True, "files": []}
    resp = _dispatch("database", "list", {})
    assert resp["body"]["success"] is True


def test_legacy_other_tools_redirect() -> None:
    resp = _dispatch("other_tools", "view", {})
    assert "other-tools" in resp["body"]["redirect"]


def test_legacy_excel_decompose_view() -> None:
    resp = _dispatch("excel_decompose", "view", {})
    assert "excel" in resp["body"]["redirect"]


def test_legacy_shipment_template_view() -> None:
    resp = _dispatch("shipment_template", "view", {})
    assert resp["body"]["success"] is True
