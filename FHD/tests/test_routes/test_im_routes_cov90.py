"""Coverage-focused behavior tests for app.fastapi_routes.im_routes.

Targets previously-uncovered success/error branches in the IM REST routes,
the admin super-employee routes, the AI group routes, and helper functions.

All external dependencies (DB session factory, application services, ws hub,
mobile push) are mocked; tests are deterministic and offline.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.im_routes import router


@pytest.fixture
def client():
    """TestClient with require_identified_user overridden to a fixed user (uid=1)."""
    from app.infrastructure.auth.dependencies import require_identified_user

    app = FastAPI()
    app.include_router(router)
    mock_user = MagicMock()
    mock_user.user_id = 1
    app.dependency_overrides[require_identified_user] = lambda: mock_user

    import app.fastapi_routes.im_routes as mod

    mod._schema_ready = True
    return TestClient(app, raise_server_exceptions=False)


def _patch_db():
    """Patch HostSessionLocal so the route's db = HostSessionLocal() is a mock."""
    return patch("app.fastapi_routes.im_routes.HostSessionLocal", return_value=MagicMock())


# ---------------------------------------------------------------------------
# _is_admin_customer_service_session — exception branch (lines 53-54)
# ---------------------------------------------------------------------------


class TestIsAdminCustomerServiceSessionExceptionBranch:
    def test_db_query_raises_returns_false(self):
        import app.fastapi_routes.im_routes as mod

        request = MagicMock()
        db = MagicMock()
        # session_id_from_request will return a sid; db.query then raises.
        db.query.side_effect = RuntimeError("db down")
        with patch(
            "app.infrastructure.auth.dependencies.session_id_from_request",
            return_value="some-sid",
        ):
            assert mod._is_admin_customer_service_session(request, db) is False

    def test_no_session_id_returns_false(self):
        import app.fastapi_routes.im_routes as mod

        request = MagicMock()
        db = MagicMock()
        with patch(
            "app.infrastructure.auth.dependencies.session_id_from_request",
            return_value=None,
        ):
            assert mod._is_admin_customer_service_session(request, db) is False
        # db should never have been queried when there's no sid.
        db.query.assert_not_called()


# ---------------------------------------------------------------------------
# _resolve_ws_user_id — facade ImportError fallback (lines 88-89)
# ---------------------------------------------------------------------------


class TestResolveWsUserIdFacadeFallback:
    def test_falls_back_to_facade_session_service(self):
        import builtins

        from app.fastapi_routes.im_routes import _resolve_ws_user_id

        ws = MagicMock()
        ws.query_params = {"user_id": "", "session_id": "sid-1"}
        ws.cookies = {"session_id": "sid-1"}

        mock_user = MagicMock()
        mock_user.id = 9
        mock_facade_svc = MagicMock()
        mock_facade_svc.validate_session.return_value = mock_user

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            # Force the primary `from app.services import get_session_service`
            # path to fail so the facade fallback executes.
            if name == "app.services":
                raise ImportError("blocked for test")
            return real_import(name, *args, **kwargs)

        with (
            patch(
                "app.infrastructure.auth.dependencies._allow_x_user_id_header",
                return_value=False,
            ),
            patch("app.fastapi_routes.im_routes.Config", SESSION_COOKIE_NAME="session_id"),
            patch(
                "app.application.facades.session_facade.get_session_service",
                return_value=mock_facade_svc,
            ),
            patch.object(builtins, "__import__", side_effect=fake_import),
        ):
            result = _resolve_ws_user_id(ws)

        assert result == 9
        mock_facade_svc.validate_session.assert_called_once_with("sid-1")


# ---------------------------------------------------------------------------
# _notify_offline_im_members — mobile_push facade fallback (lines 114-115)
# ---------------------------------------------------------------------------


class TestNotifyOfflineFacadeFallback:
    @pytest.mark.asyncio
    async def test_falls_back_to_app_service_notify(self):
        import builtins

        from app.fastapi_routes.im_routes import _notify_offline_im_members

        fallback_notify = MagicMock()
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "app.services.mobile_push":
                raise ImportError("blocked for test")
            return real_import(name, *args, **kwargs)

        with (
            patch("app.fastapi_routes.im_routes.im_ws_hub") as mock_hub,
            patch(
                "app.application.mobile_push_app_service.notify_mobile_user",
                fallback_notify,
            ),
            patch.object(builtins, "__import__", side_effect=fake_import),
        ):
            mock_hub.connected_user_ids.return_value = [1]
            # member 2 is offline -> fallback notify invoked once
            await _notify_offline_im_members([1, 2], 1, "hi there")

        assert fallback_notify.call_count == 1
        assert fallback_notify.call_args.kwargs["body"] == "hi there"

    @pytest.mark.asyncio
    async def test_truncates_preview_to_120_chars(self):
        from app.fastapi_routes.im_routes import _notify_offline_im_members

        long_body = "x" * 300
        with (
            patch("app.fastapi_routes.im_routes.im_ws_hub") as mock_hub,
            patch("app.services.mobile_push.notify_user") as mock_notify,
        ):
            mock_hub.connected_user_ids.return_value = [1]
            await _notify_offline_im_members([1, 2], 1, long_body)

        assert mock_notify.call_count == 1
        assert mock_notify.call_args.kwargs["body"] == "x" * 120


# ---------------------------------------------------------------------------
# im_list_conversations / contacts / unread — RECOVERABLE_ERRORS branch
# (lines 176-178, 198-200)
# ---------------------------------------------------------------------------


class TestListRecoverableErrors:
    def test_list_conversations_recoverable_error_500(self, client):
        with (
            _patch_db(),
            patch("app.fastapi_routes.im_routes.ImApplicationService") as svc_cls,
            patch(
                "app.fastapi_routes.im_routes._include_enterprise_dedicated_cs",
                return_value=True,
            ),
        ):
            svc = MagicMock()
            svc.list_conversations.side_effect = RuntimeError("boom")
            svc_cls.return_value = svc
            resp = client.get("/api/im/conversations")
        assert resp.status_code == 500
        body = resp.json()
        assert body["success"] is False
        assert "boom" in body["message"]

    def test_list_contacts_recoverable_error_500(self, client):
        with (
            _patch_db(),
            patch("app.fastapi_routes.im_routes.ImApplicationService") as svc_cls,
            patch(
                "app.fastapi_routes.im_routes._include_enterprise_dedicated_cs",
                return_value=True,
            ),
        ):
            svc = MagicMock()
            svc.list_contacts.side_effect = RuntimeError("contacts down")
            svc_cls.return_value = svc
            resp = client.get("/api/im/contacts")
        assert resp.status_code == 500
        assert "contacts down" in resp.json()["message"]

    def test_list_contacts_keyword_filter(self, client):
        with (
            _patch_db(),
            patch("app.fastapi_routes.im_routes.ImApplicationService") as svc_cls,
            patch(
                "app.fastapi_routes.im_routes._include_enterprise_dedicated_cs",
                return_value=True,
            ),
        ):
            svc = MagicMock()
            svc.list_contacts.return_value = [
                {"display_name": "Alice", "username": "alice"},
                {"display_name": "Bob", "username": "bob"},
            ]
            svc_cls.return_value = svc
            resp = client.get("/api/im/contacts", params={"q": "ali"})
        assert resp.status_code == 200
        contacts = resp.json()["contacts"]
        assert len(contacts) == 1
        assert contacts[0]["username"] == "alice"

    def test_unread_total_recoverable_error_500(self, client):
        with (
            _patch_db(),
            patch("app.fastapi_routes.im_routes.ImApplicationService") as svc_cls,
            patch(
                "app.fastapi_routes.im_routes._include_enterprise_dedicated_cs",
                return_value=True,
            ),
        ):
            svc = MagicMock()
            svc.list_conversations.side_effect = RuntimeError("unread down")
            svc_cls.return_value = svc
            resp = client.get("/api/im/unread-total")
        assert resp.status_code == 500
        assert "unread down" in resp.json()["message"]


# ---------------------------------------------------------------------------
# im_create_direct — ValueError(400) and RECOVERABLE(500) (lines 219-223)
# ---------------------------------------------------------------------------


class TestCreateDirectErrors:
    def test_create_direct_success(self, client):
        with (
            _patch_db(),
            patch("app.fastapi_routes.im_routes.ImApplicationService") as svc_cls,
        ):
            svc = MagicMock()
            svc.get_or_create_direct.return_value = {"id": 7, "kind": "direct"}
            svc_cls.return_value = svc
            resp = client.post("/api/im/conversations/direct", json={"peer_user_id": 2})
        assert resp.status_code == 200
        assert resp.json()["conversation"]["id"] == 7
        svc.get_or_create_direct.assert_called_once_with(1, 2)

    def test_create_direct_recoverable_error_500(self, client):
        with (
            _patch_db(),
            patch("app.fastapi_routes.im_routes.ImApplicationService") as svc_cls,
        ):
            svc = MagicMock()
            svc.get_or_create_direct.side_effect = RuntimeError("db gone")
            svc_cls.return_value = svc
            resp = client.post("/api/im/conversations/direct", json={"peer_user_id": 2})
        assert resp.status_code == 500
        assert "db gone" in resp.json()["message"]


# ---------------------------------------------------------------------------
# im_list_messages — success / PermissionError(403) / RECOVERABLE(500)
# (lines 243-247)
# ---------------------------------------------------------------------------


class TestListMessages:
    def test_success(self, client):
        with (
            _patch_db(),
            patch("app.fastapi_routes.im_routes.ImApplicationService") as svc_cls,
        ):
            svc = MagicMock()
            svc.list_messages.return_value = [{"id": 1, "body": "hi"}]
            svc_cls.return_value = svc
            resp = client.get("/api/im/conversations/5/messages")
        assert resp.status_code == 200
        assert resp.json()["messages"][0]["body"] == "hi"
        svc.list_messages.assert_called_once_with(5, 1, limit=50, before_id=None)

    def test_permission_denied_403(self, client):
        with (
            _patch_db(),
            patch("app.fastapi_routes.im_routes.ImApplicationService") as svc_cls,
        ):
            svc = MagicMock()
            svc.list_messages.side_effect = PermissionError("not a member")
            svc_cls.return_value = svc
            resp = client.get("/api/im/conversations/5/messages")
        assert resp.status_code == 403
        assert "not a member" in resp.json()["message"]

    def test_recoverable_error_500(self, client):
        with (
            _patch_db(),
            patch("app.fastapi_routes.im_routes.ImApplicationService") as svc_cls,
        ):
            svc = MagicMock()
            svc.list_messages.side_effect = RuntimeError("query failed")
            svc_cls.return_value = svc
            resp = client.get("/api/im/conversations/5/messages")
        assert resp.status_code == 500
        assert "query failed" in resp.json()["message"]


# ---------------------------------------------------------------------------
# im_send_message — success (fan-out) / Permission / Value / RECOVERABLE
# (lines 283-289)
# ---------------------------------------------------------------------------


class TestSendMessage:
    def test_success_fans_out_to_other_members(self, client):
        result = {
            "message": {"id": 11, "body": "hello"},
            "updated_at_ms": 1234,
            "member_user_ids": [1, 2, 3],
        }
        with (
            _patch_db(),
            patch("app.fastapi_routes.im_routes.ImApplicationService") as svc_cls,
            patch("app.fastapi_routes.im_routes.im_ws_hub") as mock_hub,
            patch(
                "app.fastapi_routes.im_routes._notify_offline_im_members",
                new=AsyncMock(),
            ) as mock_notify,
        ):
            svc = MagicMock()
            svc.send_message.return_value = result
            svc_cls.return_value = svc
            mock_hub.send_to_user = AsyncMock()
            resp = client.post("/api/im/conversations/9/messages", json={"body": "hello"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["message"]["id"] == 11
        # members 2 and 3 each get legacy + sync payloads (4 sends); not sender(1)
        assert mock_hub.send_to_user.await_count == 4
        mock_notify.assert_awaited_once()

    def test_permission_denied_403(self, client):
        with (
            _patch_db(),
            patch("app.fastapi_routes.im_routes.ImApplicationService") as svc_cls,
        ):
            svc = MagicMock()
            svc.send_message.side_effect = PermissionError("forbidden")
            svc_cls.return_value = svc
            resp = client.post("/api/im/conversations/9/messages", json={"body": "x"})
        assert resp.status_code == 403
        assert "forbidden" in resp.json()["message"]

    def test_value_error_400(self, client):
        with (
            _patch_db(),
            patch("app.fastapi_routes.im_routes.ImApplicationService") as svc_cls,
        ):
            svc = MagicMock()
            svc.send_message.side_effect = ValueError("empty body")
            svc_cls.return_value = svc
            resp = client.post("/api/im/conversations/9/messages", json={"body": ""})
        assert resp.status_code == 400
        assert "empty body" in resp.json()["message"]

    def test_recoverable_error_500(self, client):
        with (
            _patch_db(),
            patch("app.fastapi_routes.im_routes.ImApplicationService") as svc_cls,
        ):
            svc = MagicMock()
            svc.send_message.side_effect = RuntimeError("send failed")
            svc_cls.return_value = svc
            resp = client.post("/api/im/conversations/9/messages", json={"body": "x"})
        assert resp.status_code == 500
        assert "send failed" in resp.json()["message"]


# ---------------------------------------------------------------------------
# im_mark_read — success (fan-out) / Permission(403) / RECOVERABLE(500)
# (lines 319-321)
# ---------------------------------------------------------------------------


class TestMarkRead:
    def test_success_fans_out(self, client):
        result = {
            "last_read_message_id": 20,
            "updated_at_ms": 9999,
            "member_user_ids": [1, 2],
        }
        with (
            _patch_db(),
            patch("app.fastapi_routes.im_routes.ImApplicationService") as svc_cls,
            patch("app.fastapi_routes.im_routes.im_ws_hub") as mock_hub,
        ):
            svc = MagicMock()
            svc.mark_read.return_value = result
            svc_cls.return_value = svc
            mock_hub.send_to_user = AsyncMock()
            resp = client.post("/api/im/conversations/3/read", json={"last_message_id": 20})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["last_read_message_id"] == 20
        # only member 2 (not sender 1) gets a read receipt
        assert mock_hub.send_to_user.await_count == 1
        svc.mark_read.assert_called_once_with(3, 1, 20)

    def test_permission_denied_403(self, client):
        with (
            _patch_db(),
            patch("app.fastapi_routes.im_routes.ImApplicationService") as svc_cls,
        ):
            svc = MagicMock()
            svc.mark_read.side_effect = PermissionError("no access")
            svc_cls.return_value = svc
            resp = client.post("/api/im/conversations/3/read", json={"last_message_id": 1})
        assert resp.status_code == 403
        assert "no access" in resp.json()["message"]

    def test_recoverable_error_500(self, client):
        with (
            _patch_db(),
            patch("app.fastapi_routes.im_routes.ImApplicationService") as svc_cls,
        ):
            svc = MagicMock()
            svc.mark_read.side_effect = RuntimeError("read failed")
            svc_cls.return_value = svc
            resp = client.post("/api/im/conversations/3/read", json={"last_message_id": 1})
        assert resp.status_code == 500
        assert "read failed" in resp.json()["message"]


# ---------------------------------------------------------------------------
# codex_super_employee_messages — RECOVERABLE branch (lines 341-343)
# ---------------------------------------------------------------------------


class TestCodexMessagesError:
    def test_recoverable_error_500(self, client):
        with (
            _patch_db(),
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.CodexSuperEmployeeService") as svc_cls,
        ):
            svc = MagicMock()
            svc.list_messages.side_effect = RuntimeError("codex down")
            svc_cls.return_value = svc
            resp = client.get("/api/admin/codex-super-employee/messages")
        assert resp.status_code == 500
        assert "codex down" in resp.json()["message"]

    def test_codex_invoke_value_error_400(self, client):
        with (
            _patch_db(),
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.CodexSuperEmployeeService") as svc_cls,
        ):
            svc = MagicMock()
            svc.invoke.side_effect = ValueError("empty message")
            svc_cls.return_value = svc
            resp = client.post("/api/admin/codex-super-employee/messages", json={"message": ""})
        assert resp.status_code == 400
        assert "empty message" in resp.json()["message"]


# ---------------------------------------------------------------------------
# claude_super_employee_messages / invoke (lines 381-419)
# ---------------------------------------------------------------------------


class TestClaudeSuperEmployee:
    def test_messages_rejects_non_admin(self, client):
        with (
            _patch_db(),
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=False,
            ),
        ):
            resp = client.get("/api/admin/claude-super-employee/messages")
        assert resp.status_code == 403
        assert "管理端" in resp.json()["message"]

    def test_messages_success_for_admin(self, client):
        with (
            _patch_db(),
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.ClaudeSuperEmployeeService") as svc_cls,
        ):
            svc = MagicMock()
            svc.list_messages.return_value = [{"id": "c1", "body": "hi"}]
            svc_cls.return_value = svc
            resp = client.get("/api/admin/claude-super-employee/messages")
        assert resp.status_code == 200
        assert resp.json()["messages"][0]["body"] == "hi"
        svc.list_messages.assert_called_once_with(user_id=1, limit=80)

    def test_messages_recoverable_error_500(self, client):
        with (
            _patch_db(),
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.ClaudeSuperEmployeeService") as svc_cls,
        ):
            svc = MagicMock()
            svc.list_messages.side_effect = RuntimeError("claude down")
            svc_cls.return_value = svc
            resp = client.get("/api/admin/claude-super-employee/messages")
        assert resp.status_code == 500
        assert "claude down" in resp.json()["message"]

    def test_invoke_rejects_non_admin(self, client):
        with (
            _patch_db(),
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=False,
            ),
        ):
            resp = client.post("/api/admin/claude-super-employee/messages", json={"message": "hi"})
        assert resp.status_code == 403

    def test_invoke_success_for_admin(self, client):
        service_result = {
            "employee": {"id": "claude-super-employee"},
            "message": {"id": "m1", "body": "fix it"},
        }
        with (
            _patch_db(),
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.ClaudeSuperEmployeeService") as svc_cls,
        ):
            svc = MagicMock()
            svc.invoke.return_value = service_result
            svc_cls.return_value = svc
            resp = client.post(
                "/api/admin/claude-super-employee/messages",
                json={"message": "fix it", "context": {"k": "v"}},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        svc.invoke.assert_called_once_with(user_id=1, message="fix it", context={"k": "v"})

    def test_invoke_value_error_400(self, client):
        with (
            _patch_db(),
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.ClaudeSuperEmployeeService") as svc_cls,
        ):
            svc = MagicMock()
            svc.invoke.side_effect = ValueError("bad input")
            svc_cls.return_value = svc
            resp = client.post("/api/admin/claude-super-employee/messages", json={"message": "x"})
        assert resp.status_code == 400
        assert "bad input" in resp.json()["message"]

    def test_invoke_recoverable_error_500(self, client):
        with (
            _patch_db(),
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.ClaudeSuperEmployeeService") as svc_cls,
        ):
            svc = MagicMock()
            svc.invoke.side_effect = RuntimeError("invoke down")
            svc_cls.return_value = svc
            resp = client.post("/api/admin/claude-super-employee/messages", json={"message": "x"})
        assert resp.status_code == 500
        assert "invoke down" in resp.json()["message"]

    def test_invoke_non_dict_context_defaults_to_empty(self, client):
        with (
            _patch_db(),
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.ClaudeSuperEmployeeService") as svc_cls,
        ):
            svc = MagicMock()
            svc.invoke.return_value = {"message": {"id": "m"}}
            svc_cls.return_value = svc
            resp = client.post(
                "/api/admin/claude-super-employee/messages",
                json={"message": "hi", "context": "not-a-dict"},
            )
        assert resp.status_code == 200
        svc.invoke.assert_called_once_with(user_id=1, message="hi", context={})


# ---------------------------------------------------------------------------
# _ai_group_guard + AI group routes (lines 427-432, 437-565)
# ---------------------------------------------------------------------------


class TestAiGroupsList:
    def test_denied_when_not_admin(self, client):
        with (
            _patch_db(),
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=False,
            ),
        ):
            resp = client.get("/api/admin/ai-groups")
        assert resp.status_code == 403

    def test_success(self, client):
        with (
            patch("app.fastapi_routes.im_routes._ai_group_guard", return_value=None),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as svc_cls,
        ):
            svc = MagicMock()
            svc.list_groups.return_value = [{"id": "g1", "name": "团队"}]
            svc_cls.return_value = svc
            resp = client.get("/api/admin/ai-groups")
        assert resp.status_code == 200
        assert resp.json()["groups"][0]["id"] == "g1"
        svc.list_groups.assert_called_once_with(user_id=1)

    def test_recoverable_error_500(self, client):
        with (
            patch("app.fastapi_routes.im_routes._ai_group_guard", return_value=None),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as svc_cls,
        ):
            svc = MagicMock()
            svc.list_groups.side_effect = RuntimeError("groups down")
            svc_cls.return_value = svc
            resp = client.get("/api/admin/ai-groups")
        assert resp.status_code == 500
        assert "groups down" in resp.json()["message"]


class TestAiGroupsCreate:
    def test_denied_when_not_admin(self, client):
        with patch("app.fastapi_routes.im_routes._ai_group_guard") as guard:
            from fastapi.responses import JSONResponse

            guard.return_value = JSONResponse(
                {"success": False, "message": "仅管理端可调用 Codex 超级员工"},
                status_code=403,
            )
            resp = client.post("/api/admin/ai-groups", json={"name": "x"})
        assert resp.status_code == 403

    def test_success(self, client):
        with (
            patch("app.fastapi_routes.im_routes._ai_group_guard", return_value=None),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as svc_cls,
        ):
            svc = MagicMock()
            svc.create_group.return_value = {"id": "g2", "name": "新组"}
            svc_cls.return_value = svc
            resp = client.post("/api/admin/ai-groups", json={"name": "新组"})
        assert resp.status_code == 200
        assert resp.json()["group"]["id"] == "g2"
        svc.create_group.assert_called_once_with(user_id=1, name="新组")

    def test_value_error_400(self, client):
        with (
            patch("app.fastapi_routes.im_routes._ai_group_guard", return_value=None),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as svc_cls,
        ):
            svc = MagicMock()
            svc.create_group.side_effect = ValueError("name required")
            svc_cls.return_value = svc
            resp = client.post("/api/admin/ai-groups", json={"name": ""})
        assert resp.status_code == 400
        assert "name required" in resp.json()["message"]

    def test_recoverable_error_500(self, client):
        with (
            patch("app.fastapi_routes.im_routes._ai_group_guard", return_value=None),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as svc_cls,
        ):
            svc = MagicMock()
            svc.create_group.side_effect = RuntimeError("create down")
            svc_cls.return_value = svc
            resp = client.post("/api/admin/ai-groups", json={"name": "x"})
        assert resp.status_code == 500
        assert "create down" in resp.json()["message"]


class TestAiGroupMessages:
    def test_get_messages_success(self, client):
        with (
            patch("app.fastapi_routes.im_routes._ai_group_guard", return_value=None),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as svc_cls,
        ):
            svc = MagicMock()
            svc.get_messages.return_value = [{"id": "m1", "text": "hi"}]
            svc_cls.return_value = svc
            resp = client.get("/api/admin/ai-groups/g1/messages")
        assert resp.status_code == 200
        assert resp.json()["messages"][0]["text"] == "hi"
        svc.get_messages.assert_called_once_with(user_id=1, group_id="g1", limit=100)

    def test_get_messages_recoverable_error_500(self, client):
        with (
            patch("app.fastapi_routes.im_routes._ai_group_guard", return_value=None),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as svc_cls,
        ):
            svc = MagicMock()
            svc.get_messages.side_effect = RuntimeError("msgs down")
            svc_cls.return_value = svc
            resp = client.get("/api/admin/ai-groups/g1/messages")
        assert resp.status_code == 500
        assert "msgs down" in resp.json()["message"]

    def test_post_message_success(self, client):
        with (
            patch("app.fastapi_routes.im_routes._ai_group_guard", return_value=None),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as svc_cls,
        ):
            svc = MagicMock()
            svc.post_message = AsyncMock(return_value={"replies": [{"id": "r1"}]})
            svc_cls.return_value = svc
            resp = client.post(
                "/api/admin/ai-groups/g1/messages",
                json={"message": "hi", "sender_name": "Boss", "mentions": ["e1"]},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        svc.post_message.assert_awaited_once_with(
            user_id=1,
            group_id="g1",
            text="hi",
            sender_name="Boss",
            mentions=["e1"],
            dispatch=False,
        )

    def test_post_message_non_list_mentions_becomes_none(self, client):
        with (
            patch("app.fastapi_routes.im_routes._ai_group_guard", return_value=None),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as svc_cls,
        ):
            svc = MagicMock()
            svc.post_message = AsyncMock(return_value={"replies": []})
            svc_cls.return_value = svc
            resp = client.post(
                "/api/admin/ai-groups/g1/messages",
                json={"message": "hi", "mentions": "notalist"},
            )
        assert resp.status_code == 200
        assert svc.post_message.await_args.kwargs["mentions"] is None

    def test_post_message_value_error_400(self, client):
        with (
            patch("app.fastapi_routes.im_routes._ai_group_guard", return_value=None),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as svc_cls,
        ):
            svc = MagicMock()
            svc.post_message = AsyncMock(side_effect=ValueError("empty"))
            svc_cls.return_value = svc
            resp = client.post("/api/admin/ai-groups/g1/messages", json={"message": ""})
        assert resp.status_code == 400
        assert "empty" in resp.json()["message"]

    def test_post_message_recoverable_error_500(self, client):
        with (
            patch("app.fastapi_routes.im_routes._ai_group_guard", return_value=None),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as svc_cls,
        ):
            svc = MagicMock()
            svc.post_message = AsyncMock(side_effect=RuntimeError("post down"))
            svc_cls.return_value = svc
            resp = client.post("/api/admin/ai-groups/g1/messages", json={"message": "hi"})
        assert resp.status_code == 500
        assert "post down" in resp.json()["message"]


class TestAiGroupMembers:
    def test_add_member_success(self, client):
        with (
            patch("app.fastapi_routes.im_routes._ai_group_guard", return_value=None),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as svc_cls,
        ):
            svc = MagicMock()
            svc.add_member.return_value = {"id": "g1", "members": [{"employee_id": "e1"}]}
            svc_cls.return_value = svc
            resp = client.post(
                "/api/admin/ai-groups/g1/members",
                json={"employee_id": "e1", "mod_id": "m1", "name": "Bot"},
            )
        assert resp.status_code == 200
        assert resp.json()["group"]["id"] == "g1"
        called = svc.add_member.call_args.kwargs
        assert called["user_id"] == 1
        assert called["group_id"] == "g1"
        assert called["member"]["employee_id"] == "e1"
        assert called["member"]["name"] == "Bot"

    def test_add_member_value_error_400(self, client):
        with (
            patch("app.fastapi_routes.im_routes._ai_group_guard", return_value=None),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as svc_cls,
        ):
            svc = MagicMock()
            svc.add_member.side_effect = ValueError("dup member")
            svc_cls.return_value = svc
            resp = client.post("/api/admin/ai-groups/g1/members", json={"employee_id": "e1"})
        assert resp.status_code == 400
        assert "dup member" in resp.json()["message"]

    def test_add_member_recoverable_error_500(self, client):
        with (
            patch("app.fastapi_routes.im_routes._ai_group_guard", return_value=None),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as svc_cls,
        ):
            svc = MagicMock()
            svc.add_member.side_effect = RuntimeError("add down")
            svc_cls.return_value = svc
            resp = client.post("/api/admin/ai-groups/g1/members", json={"employee_id": "e1"})
        assert resp.status_code == 500
        assert "add down" in resp.json()["message"]

    def test_remove_member_success(self, client):
        with (
            patch("app.fastapi_routes.im_routes._ai_group_guard", return_value=None),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as svc_cls,
        ):
            svc = MagicMock()
            svc.remove_member.return_value = {"id": "g1", "members": []}
            svc_cls.return_value = svc
            resp = client.delete("/api/admin/ai-groups/g1/members/e1")
        assert resp.status_code == 200
        assert resp.json()["group"]["members"] == []
        svc.remove_member.assert_called_once_with(user_id=1, group_id="g1", employee_id="e1")

    def test_remove_member_value_error_400(self, client):
        with (
            patch("app.fastapi_routes.im_routes._ai_group_guard", return_value=None),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as svc_cls,
        ):
            svc = MagicMock()
            svc.remove_member.side_effect = ValueError("no such member")
            svc_cls.return_value = svc
            resp = client.delete("/api/admin/ai-groups/g1/members/e1")
        assert resp.status_code == 400
        assert "no such member" in resp.json()["message"]

    def test_remove_member_recoverable_error_500(self, client):
        with (
            patch("app.fastapi_routes.im_routes._ai_group_guard", return_value=None),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as svc_cls,
        ):
            svc = MagicMock()
            svc.remove_member.side_effect = RuntimeError("remove down")
            svc_cls.return_value = svc
            resp = client.delete("/api/admin/ai-groups/g1/members/e1")
        assert resp.status_code == 500
        assert "remove down" in resp.json()["message"]

    def test_remove_member_denied_when_not_admin(self, client):
        with (
            _patch_db(),
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=False,
            ),
        ):
            resp = client.delete("/api/admin/ai-groups/g1/members/e1")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# _ai_group_guard direct unit (lines 427-432)
# ---------------------------------------------------------------------------


class TestAiGroupGuard:
    def test_returns_none_when_admin(self):
        import app.fastapi_routes.im_routes as mod

        request = MagicMock()
        with (
            _patch_db(),
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
        ):
            assert mod._ai_group_guard(request) is None

    def test_returns_denied_when_not_admin(self):
        from fastapi.responses import JSONResponse

        import app.fastapi_routes.im_routes as mod

        request = MagicMock()
        with (
            _patch_db(),
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=False,
            ),
        ):
            denied = mod._ai_group_guard(request)
        assert isinstance(denied, JSONResponse)
        assert denied.status_code == 403


# ---------------------------------------------------------------------------
# websocket — unauthorized close (lines 573-575)
# ---------------------------------------------------------------------------


class TestWebSocketUnauthorized:
    def test_unauthorized_closes_with_4401(self, client):
        from starlette.websockets import WebSocketDisconnect as StarletteWSDisconnect

        with patch("app.fastapi_routes.im_routes._resolve_ws_user_id", return_value=None):
            # Server accepts then immediately closes with code 4401; the first
            # receive on the client side raises WebSocketDisconnect carrying it.
            with client.websocket_connect("/ws/im") as ws:
                with pytest.raises(StarletteWSDisconnect) as exc_info:
                    ws.receive_text()
        assert exc_info.value.code == 4401

    def test_authorized_pings_get_pong(self, client):
        with (
            patch("app.fastapi_routes.im_routes._resolve_ws_user_id", return_value=7),
            patch("app.fastapi_routes.im_routes.im_ws_hub") as mock_hub,
        ):
            mock_hub.connect = AsyncMock()
            mock_hub.disconnect = AsyncMock()
            with client.websocket_connect("/ws/im") as ws:
                ws.send_text("ping")
                reply = ws.receive_text()
        assert reply == '{"type":"pong"}'
        mock_hub.connect.assert_awaited_once()
