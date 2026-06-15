"""COVERAGE_RAMP Phase 4 round 28: wechat starred/contacts routes,
session_account_meta enterprise CS gate, ai_chat process_chat workflow short-circuit."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.ai_chat_app_service import AIChatApplicationService
from app.application.session_account_meta import (
    is_session_market_admin,
    should_receive_enterprise_dedicated_cs,
)


def _chat_svc() -> tuple[AIChatApplicationService, MagicMock]:
    mock_ai = MagicMock()
    mock_ai.chat = AsyncMock(
        return_value={"success": True, "text": "回复", "action": "followup", "data": {}}
    )
    with (
        patch("app.application.ai_chat_app_service.get_ai_conversation_service", return_value=mock_ai),
        patch("app.application.ai_chat_app_service.LLMWorkflowPlanner"),
        patch("app.application.ai_chat_app_service.HybridRiskGate"),
        patch("app.application.ai_chat_app_service.WorkflowEngine"),
        patch("app.application.ai_chat_app_service.get_approval_service"),
    ):
        svc = AIChatApplicationService()
        svc.ai_service = mock_ai
        return svc, mock_ai


# ---------------------------------------------------------------------------
# wechat routes — starred / contacts
# ---------------------------------------------------------------------------


@patch("app.services.wechat_group_customer_bridge.build_starred_group_feed")
@patch("app.services.wechat_group_customer_bridge.sync_group_messages")
def test_wechat_starred_messages_group_sync(mock_sync: MagicMock, mock_feed: MagicMock) -> None:
    from app.fastapi_routes.domains.wechat import routes as wechat_routes

    mock_feed.return_value = [{"id": "g1"}]
    out = wechat_routes.wechat_starred_messages(
        limit=5, type="group", market_user_id=None, sync=True
    )
    assert out["success"] is True
    assert out["filter"]["type"] == "group"
    mock_sync.assert_called_once()


@patch("app.services.wechat_group_customer_bridge.build_starred_group_feed")
@patch(
    "app.services.wechat_group_customer_bridge.sync_bound_groups_from_live_wechat",
)
def test_wechat_starred_messages_group_with_market_user(
    mock_live: MagicMock, mock_feed: MagicMock
) -> None:
    from app.fastapi_routes.domains.wechat import routes as wechat_routes

    mock_feed.return_value = []
    out = wechat_routes.wechat_starred_messages(
        type="group", sync=True, market_user_id=99, limit=3
    )
    assert out["success"] is True
    mock_live.assert_called_once_with(99, message_limit=80, mode="feed")


@patch("app.services.wechat_group_customer_bridge._latest_context_message")
def test_wechat_starred_messages_contact_feed(mock_latest: MagicMock) -> None:
    from app.fastapi_routes.domains.wechat import routes as wechat_routes

    mock_latest.side_effect = lambda msgs: msgs[0] if msgs else None
    mock_svc = MagicMock()
    mock_svc.get_contacts.return_value = [
        {"id": 1, "contact_name": "甲公司", "contact_type": "contact"},
        {"id": 2, "contact_name": "无消息"},
    ]
    mock_svc.get_contact_context.side_effect = lambda cid: (
        [{"content": "你好"}] if cid == 1 else []
    )
    with patch("app.application.get_wechat_contact_app_service", return_value=mock_svc):
        out = wechat_routes.wechat_starred_messages(limit=10, type="all", market_user_id=None, sync=False)
    assert out["success"] is True
    assert out["total"] == 1
    assert out["data"][0]["contact_name"] == "甲公司"


def test_wechat_contact_get_found_and_missing() -> None:
    from app.fastapi_routes.domains.wechat import routes as wechat_routes

    mock_svc = MagicMock()
    mock_svc.get_contact_by_id.side_effect = lambda cid: (
        {"id": 3, "contact_name": "Bob"} if cid == 3 else None
    )
    with patch("app.application.get_wechat_contact_app_service", return_value=mock_svc):
        ok = wechat_routes.wechat_contact_get_api(3)
        miss = wechat_routes.wechat_contact_get_api(99)
    assert ok["success"] is True
    assert miss.status_code == 404


def test_wechat_contacts_post_validation() -> None:
    from app.fastapi_routes.domains.wechat import routes as wechat_routes

    bad = wechat_routes.wechat_contacts_post({"contact_name": "  "})
    assert bad.status_code == 400

    mock_svc = MagicMock()
    mock_svc.add_contact.return_value = {"success": True, "id": 1}
    with patch("app.application.get_wechat_contact_app_service", return_value=mock_svc):
        ok = wechat_routes.wechat_contacts_post({"contact_name": "甲公司"})
    assert ok.status_code == 200


def test_wechat_contact_context_refresh() -> None:
    from app.fastapi_routes.domains.wechat import routes as wechat_routes

    mock_svc = MagicMock()
    mock_svc.refresh_messages = MagicMock()
    mock_svc.get_contact_context.return_value = [{"content": "x"}]
    with patch("app.application.get_wechat_contact_app_service", return_value=mock_svc):
        out = wechat_routes.wechat_contact_context_api(5, refresh=True)
    assert out["success"] is True
    assert out["count"] == 1
    mock_svc.refresh_messages.assert_called_once_with(5, limit=80)


# ---------------------------------------------------------------------------
# session_account_meta — enterprise dedicated CS
# ---------------------------------------------------------------------------


@patch("app.application.session_account_meta.load_session_account_meta")
def test_should_receive_enterprise_cs_impersonating(mock_load: MagicMock) -> None:
    mock_load.return_value = {
        "account_kind": "enterprise",
        "market_is_admin": False,
        "impersonating_market_user_id": 7,
    }
    db = MagicMock()
    assert should_receive_enterprise_dedicated_cs("sid", 1, db) is True


@patch("app.application.session_account_meta.load_session_account_meta")
def test_should_receive_enterprise_cs_admin_blocked(mock_load: MagicMock) -> None:
    mock_load.return_value = {
        "account_kind": "admin",
        "market_is_admin": True,
    }
    db = MagicMock()
    assert should_receive_enterprise_dedicated_cs("sid", 1, db) is False


@patch("app.application.session_account_meta.load_session_account_meta")
def test_should_receive_enterprise_cs_fallback_user_role(mock_load: MagicMock) -> None:
    mock_load.return_value = None
    db = MagicMock()
    db.get.return_value = SimpleNamespace(role="user")
    assert should_receive_enterprise_dedicated_cs(None, 2, db) is True
    db.get.return_value = SimpleNamespace(role="admin")
    assert should_receive_enterprise_dedicated_cs(None, 2, db) is False


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
@patch.object(AIChatApplicationService, "_try_handle_dynamic_workflow")
def test_process_chat_returns_workflow_without_llm(
    mock_wf: MagicMock, _mock_persist: MagicMock
) -> None:
    mock_wf.return_value = {
        "success": True,
        "message": "处理完成",
        "response": "工作流结果",
        "data": {"text": "工作流结果", "action": "workflow_done", "data": {}},
    }
    svc, mock_ai = _chat_svc()
    out = svc.process_chat("u1", "导入数据库", source="pro", context={})
    assert out["success"] is True
    assert "工作流" in out["response"]
    mock_ai.chat.assert_not_called()


@patch.object(AIChatApplicationService, "_persist_chat_turn")
def test_process_chat_empty_message(_mock_persist: MagicMock) -> None:
    svc, _mock_ai = _chat_svc()
    out = svc.process_chat("u1", "")
    assert out["success"] is False
    assert "不能为空" in out["message"]
