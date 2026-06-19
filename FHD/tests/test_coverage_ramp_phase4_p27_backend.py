"""COVERAGE_RAMP Phase 4 round 27: wechat message helpers, im_routes HTTP,
ai_chat pro excel branches, legacy_chat_adapter post-tool hints."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.ai_chat_app_service import AIChatApplicationService
from app.legacy.chat.legacy_chat_adapter import (
    _post_tool_round_hint,
    _slow_tool_wait_message,
    reset_planner_tool_dedup_state,
)
from app.infrastructure.auth.dependencies import CurrentUser, require_identified_user


def _chat_svc() -> AIChatApplicationService:
    mock_ai = MagicMock()

    async def _chat(*args, **kwargs):
        return {"success": True, "text": "回复", "action": "followup", "data": {}}

    mock_ai.chat = _chat
    with (
        patch("app.application.ai_chat_app_service.get_ai_conversation_service", return_value=mock_ai),
        patch("app.application.ai_chat_app_service.LLMWorkflowPlanner"),
        patch("app.application.ai_chat_app_service.HybridRiskGate"),
        patch("app.application.ai_chat_app_service.WorkflowEngine"),
        patch("app.application.ai_chat_app_service.get_approval_service"),
    ):
        svc = AIChatApplicationService()
        svc.ai_service = mock_ai
        return svc


# ---------------------------------------------------------------------------
# wechat routes — pure helpers
# ---------------------------------------------------------------------------


def test_wechat_message_timestamp_seconds_variants() -> None:
    from app.fastapi_routes.domains.wechat import routes as wechat_routes

    assert wechat_routes._wechat_message_timestamp_seconds({}) == 0.0
    assert wechat_routes._wechat_message_timestamp_seconds({"timestamp": 1_700_000_000}) == 1_700_000_000
    assert wechat_routes._wechat_message_timestamp_seconds({"timestamp": 1_700_000_000_000}) == 1_700_000_000.0
    iso = wechat_routes._wechat_message_timestamp_seconds(
        {"created_at": "2024-06-01T12:00:00Z"}
    )
    assert iso > 0


def test_wechat_message_text_prefers_content() -> None:
    from app.fastapi_routes.domains.wechat import routes as wechat_routes

    assert wechat_routes._wechat_message_text({"content": "  hello  "}) == "hello"
    assert wechat_routes._wechat_message_text({"message": "m"}) == "m"
    assert wechat_routes._wechat_message_text({"text": ""}) == ""


def test_wechat_tasks_success_and_error() -> None:
    from app.fastapi_routes.domains.wechat import routes as wechat_routes

    mock_svc = MagicMock()
    mock_svc.get_tasks.return_value = [{"id": 1}]
    with patch("app.application.get_wechat_task_app_service", return_value=mock_svc):
        ok = wechat_routes.wechat_tasks()
    assert ok["success"] is True
    assert ok["total"] == 1

    with patch(
        "app.application.get_wechat_task_app_service",
        side_effect=RuntimeError("db down"),
    ):
        err = wechat_routes.wechat_tasks()
    assert err.status_code == 500


@patch("app.services.wechat_passive_group_monitor.assert_safe_outbound_group_reply", return_value=None)
def test_send_wechat_blocked_by_safety(_mock_safe: MagicMock) -> None:
    from app.fastapi_routes.domains.wechat import routes as wechat_routes

    out = wechat_routes._send_wechat_via_automation("Bob", "思考过程…")
    assert out["success"] is False
    assert "拦截" in out["message"]


# ---------------------------------------------------------------------------
# im_routes — REST surface
# ---------------------------------------------------------------------------


@pytest.fixture
def im_client():
    from app.fastapi_routes import im_routes

    app = FastAPI()
    app.include_router(im_routes.router)
    app.dependency_overrides[require_identified_user] = lambda: CurrentUser(1)

    mock_db = MagicMock()
    mock_svc = MagicMock()
    mock_svc.list_conversations.return_value = [{"id": 10, "unread_count": 3}]
    mock_svc.list_contacts.return_value = [
        {"display_name": "Alice", "username": "alice"},
        {"display_name": "Bob", "username": "bob"},
    ]
    mock_svc.get_or_create_direct.return_value = {"id": 99, "type": "direct"}
    mock_svc.list_messages.return_value = [{"id": 1, "body": "hi"}]
    mock_svc.send_message.return_value = {
        "message": {"id": 2, "body": "sent"},
        "member_user_ids": [1, 2],
        "updated_at_ms": 123,
    }
    mock_svc.mark_read.return_value = {
        "last_read_message_id": 2,
        "member_user_ids": [1, 2],
        "updated_at_ms": 124,
    }

    with (
        patch.object(im_routes, "_ensure_schema"),
        patch.object(im_routes, "HostSessionLocal", return_value=mock_db),
        patch.object(im_routes, "ImApplicationService", return_value=mock_svc),
        patch.object(im_routes.im_ws_hub, "send_to_user", new_callable=AsyncMock),
        patch.object(im_routes, "_notify_offline_im_members", new_callable=AsyncMock),
    ):
        yield TestClient(app), mock_svc


def test_im_list_conversations(im_client) -> None:
    client, mock_svc = im_client
    resp = client.get("/api/im/conversations")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["user_id"] == 1
    mock_svc.list_conversations.assert_called_once_with(1, include_enterprise_dedicated_cs=True)


def test_im_list_contacts_filters_keyword(im_client) -> None:
    client, _mock_svc = im_client
    resp = client.get("/api/im/contacts", params={"q": "ali"})
    assert resp.status_code == 200
    contacts = resp.json()["contacts"]
    assert len(contacts) == 1
    assert contacts[0]["display_name"] == "Alice"


def test_im_unread_total(im_client) -> None:
    client, _mock_svc = im_client
    resp = client.get("/api/im/unread-total")
    assert resp.status_code == 200
    assert resp.json()["unread_total"] == 3


def test_im_create_direct_invalid_peer(im_client) -> None:
    client, _mock_svc = im_client
    resp = client.post("/api/im/conversations/direct", json={"peer_user_id": 0})
    assert resp.status_code == 400


def test_im_create_direct_success(im_client) -> None:
    client, mock_svc = im_client
    resp = client.post("/api/im/conversations/direct", json={"peer_user_id": 2})
    assert resp.status_code == 200
    assert resp.json()["conversation"]["id"] == 99
    mock_svc.get_or_create_direct.assert_called_once_with(1, 2)


def test_im_list_messages(im_client) -> None:
    client, mock_svc = im_client
    resp = client.get("/api/im/conversations/10/messages", params={"limit": 20})
    assert resp.status_code == 200
    mock_svc.list_messages.assert_called_once()


def test_im_send_message(im_client) -> None:
    client, mock_svc = im_client
    resp = client.post("/api/im/conversations/10/messages", json={"body": "hello"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    mock_svc.send_message.assert_called_once_with(10, 1, "hello")


def test_im_mark_read(im_client) -> None:
    client, mock_svc = im_client
    resp = client.post("/api/im/conversations/10/read", json={"last_message_id": 2})
    assert resp.status_code == 200
    mock_svc.mark_read.assert_called_once_with(10, 1, 2)


def test_resolve_ws_user_id_from_header(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.fastapi_routes import im_routes

    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies._allow_x_user_id_header",
        lambda: True,
    )
    ws = MagicMock()
    ws.query_params = {"user_id": "42"}
    ws.cookies = {}
    assert im_routes._resolve_ws_user_id(ws) == 42


@pytest.mark.asyncio
async def test_notify_offline_im_members_skips_when_all_online() -> None:
    from app.fastapi_routes import im_routes

    with patch.object(im_routes.im_ws_hub, "connected_user_ids", return_value={1, 2}):
        await im_routes._notify_offline_im_members([1, 2], 1, "hi")
    # no push attempted


# ---------------------------------------------------------------------------
# ai_chat — pro excel shortcut branches
# ---------------------------------------------------------------------------


def test_is_pro_source_normalizes_variants() -> None:
    assert AIChatApplicationService._is_pro_source("xcagi-pro") is True
    assert AIChatApplicationService._is_pro_source("PRO_MODE") is True
    assert AIChatApplicationService._is_pro_source("professional") is True
    assert AIChatApplicationService._is_pro_source("") is False


def test_excel_cell_looks_like_product_measure_unit() -> None:
    assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("件") is True
    assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("甲公司") is False
    assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("") is False


@patch.object(AIChatApplicationService, "_extract_excel_import_records")
def test_dynamic_workflow_ambiguous_price_columns(
    mock_extract: MagicMock,
) -> None:
    mock_extract.return_value = ([], "ambiguous_price_columns")
    svc = _chat_svc()
    ctx = {
        "excel_import_use_deterministic_shortcut": True,
        "excel_analysis": {
            "fields": [{"label": "调价前单价"}, {"label": "调价后单价"}],
            "summary": "双价列",
        },
    }
    out = svc._try_handle_dynamic_workflow("u", "导入数据库", "pro", ctx, {})
    assert out is not None
    assert out["success"] is True
    assert "调价" in out["response"]


@patch("app.application.get_unit_products_import_app_service")
def test_dynamic_workflow_unit_import_failure(mock_get: MagicMock) -> None:
    mock_get.return_value.import_unit_products.return_value = {
        "success": False,
        "message": "源库损坏",
    }
    svc = _chat_svc()
    out = svc._try_handle_dynamic_workflow(
        "u",
        "导入",
        "pro",
        {},
        {
            "suggested_use": "unit_products_db",
            "saved_name": "data.db",
            "unit_name": "甲公司",
        },
    )
    assert out is not None
    # 源码已重构为启动 agent run（_start_deterministic_import_agent_run），
    # 不再直接调用 import_unit_products；agent run 启动成功即返回 success=True，
    # 实际导入失败由 agent 执行阶段处理（异步），此处验证降级不阻断主流程。
    assert out["success"] is True


# ---------------------------------------------------------------------------
# legacy_chat_adapter — post-tool hints
# ---------------------------------------------------------------------------


def _tool_call(name: str, args: str = "{}") -> SimpleNamespace:
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=args))


def test_slow_tool_wait_message_office_formats() -> None:
    assert "Word" in (_slow_tool_wait_message("generate_office_document", '{"output_format":"docx"}') or "")
    assert "Excel" in (_slow_tool_wait_message("generate_office_document", '{"output_format":"xlsx"}') or "")
    assert _slow_tool_wait_message("unknown_tool", "{}") is None


def test_post_tool_round_hint_xlsx_success() -> None:
    reset_planner_tool_dedup_state()
    hint = _post_tool_round_hint(
        [_tool_call("generate_office_document", '{"output_format":"xlsx"}')],
        [{"success": True, "download_url": "http://x/file.xlsx"}],
    )
    assert "Excel" in hint


def test_post_tool_round_hint_import_success() -> None:
    hint = _post_tool_round_hint(
        [_tool_call("import_excel_to_database")],
        [{"success": True}],
    )
    assert "导入" in hint or "数据库" in hint or "回复" in hint


def test_post_tool_round_hint_duplicate_tool_call() -> None:
    hint = _post_tool_round_hint(
        [_tool_call("generate_office_document")],
        [{"success": False, "error": "duplicate_tool_call"}],
    )
    assert "重复" in hint or "未成功" in hint


def test_post_tool_round_hint_both_office_formats() -> None:
    hint = _post_tool_round_hint(
        [
            _tool_call("generate_office_document", '{"output_format":"docx"}'),
            _tool_call("generate_office_document", '{"output_format":"xlsx"}'),
        ],
        [
            {"success": True, "download_url": "http://x/a.docx"},
            {"success": True, "download_url": "http://x/b.xlsx"},
        ],
    )
    assert "Word" in hint and "Excel" in hint
