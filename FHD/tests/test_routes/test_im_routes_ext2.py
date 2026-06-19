"""Tests for app.fastapi_routes.im_routes — coverage ramp."""

from __future__ import annotations

from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from app.fastapi_routes.im_routes import (
    _uid,
    _ensure_schema,
    _resolve_ws_user_id,
    _notify_offline_im_members,
    router,
)


# ---------------------------------------------------------------------------
# _uid
# ---------------------------------------------------------------------------


class TestUid:
    def test_returns_int_user_id(self):
        user = MagicMock()
        user.user_id = 42
        assert _uid(user) == 42

    def test_raises_when_user_id_is_none(self):
        user = MagicMock()
        user.user_id = None
        with pytest.raises(ValueError, match="user_id required"):
            _uid(user)


# ---------------------------------------------------------------------------
# _ensure_schema
# ---------------------------------------------------------------------------


class TestEnsureSchema:
    def test_calls_ensure_im_tables_once(self):
        import app.fastapi_routes.im_routes as mod
        mod._schema_ready = False
        with patch("app.fastapi_routes.im_routes.ensure_im_tables") as mock_ensure, \
             patch("app.fastapi_routes.im_routes.get_host_engine", return_value=MagicMock()):
            _ensure_schema()
            mock_ensure.assert_called_once()
        mod._schema_ready = False  # reset

    def test_skips_when_already_ready(self):
        import app.fastapi_routes.im_routes as mod
        mod._schema_ready = True
        with patch("app.fastapi_routes.im_routes.ensure_im_tables") as mock_ensure:
            _ensure_schema()
            mock_ensure.assert_not_called()


# ---------------------------------------------------------------------------
# _resolve_ws_user_id
# ---------------------------------------------------------------------------


class TestResolveWsUserId:
    def test_returns_none_when_no_session(self):
        ws = MagicMock()
        ws.query_params = {"user_id": "", "session_id": ""}
        ws.cookies = {}
        with patch("app.infrastructure.auth.dependencies._allow_x_user_id_header", return_value=False), \
             patch("app.fastapi_routes.im_routes.Config", SESSION_COOKIE_NAME="session_id"):
            result = _resolve_ws_user_id(ws)
        assert result is None

    def test_returns_uid_from_query_param(self):
        ws = MagicMock()
        ws.query_params = {"user_id": "42", "session_id": ""}
        ws.cookies = {}
        with patch("app.infrastructure.auth.dependencies._allow_x_user_id_header", return_value=True):
            result = _resolve_ws_user_id(ws)
        assert result == 42

    def test_returns_uid_from_session(self):
        ws = MagicMock()
        ws.query_params = {"user_id": "", "session_id": "sess123"}
        ws.cookies = {"session_id": "sess123"}
        mock_session_svc = MagicMock()
        mock_user = MagicMock()
        mock_user.id = 7
        mock_session_svc.validate_session.return_value = mock_user
        with patch("app.infrastructure.auth.dependencies._allow_x_user_id_header", return_value=False), \
             patch("app.fastapi_routes.im_routes.Config", SESSION_COOKIE_NAME="session_id"), \
             patch("app.services.get_session_service", return_value=mock_session_svc):
            result = _resolve_ws_user_id(ws)
        assert result == 7

    def test_returns_none_when_session_invalid(self):
        ws = MagicMock()
        ws.query_params = {"user_id": "", "session_id": "bad"}
        ws.cookies = {"session_id": "bad"}
        mock_session_svc = MagicMock()
        mock_session_svc.validate_session.return_value = None
        with patch("app.infrastructure.auth.dependencies._allow_x_user_id_header", return_value=False), \
             patch("app.fastapi_routes.im_routes.Config", SESSION_COOKIE_NAME="session_id"), \
             patch("app.services.get_session_service", return_value=mock_session_svc):
            result = _resolve_ws_user_id(ws)
        assert result is None


# ---------------------------------------------------------------------------
# _notify_offline_im_members
# ---------------------------------------------------------------------------


class TestNotifyOfflineImMembers:
    @pytest.mark.asyncio
    async def test_no_offline_members(self):
        with patch("app.fastapi_routes.im_routes.im_ws_hub") as mock_hub:
            mock_hub.connected_user_ids.return_value = [1, 2]
            await _notify_offline_im_members([1, 2], 1, "hi")
        # No push should happen

    @pytest.mark.asyncio
    async def test_notifies_offline_members(self):
        with patch("app.fastapi_routes.im_routes.im_ws_hub") as mock_hub, \
             patch("app.services.mobile_push.notify_user") as mock_notify:
            mock_hub.connected_user_ids.return_value = [1]
            await _notify_offline_im_members([1, 2, 3], 1, "hello")
            assert mock_notify.call_count == 2

    @pytest.mark.asyncio
    async def test_push_error_does_not_crash(self):
        with patch("app.fastapi_routes.im_routes.im_ws_hub") as mock_hub, \
             patch("app.services.mobile_push.notify_user", side_effect=RuntimeError("push fail")):
            mock_hub.connected_user_ids.return_value = [1]
            await _notify_offline_im_members([1, 2], 1, "hello")
        # Should not raise

    @pytest.mark.asyncio
    async def test_import_error_skips_push(self):
        with patch("app.fastapi_routes.im_routes.im_ws_hub") as mock_hub, \
             patch("app.services.mobile_push.notify_user", side_effect=ImportError("no module")):
            mock_hub.connected_user_ids.return_value = [1]
            await _notify_offline_im_members([1, 2], 1, "hello")
        # Should not raise


# ---------------------------------------------------------------------------
# Route handler tests (using TestClient)
# ---------------------------------------------------------------------------


class TestImRoutes:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from app.infrastructure.auth.dependencies import require_identified_user
        app = FastAPI()
        app.include_router(router)
        mock_user = MagicMock()
        mock_user.user_id = 1
        app.dependency_overrides[require_identified_user] = lambda: mock_user
        return TestClient(app)

    def test_admin_customer_service_session_reads_current_db(self):
        import app.fastapi_routes.im_routes as mod

        request = MagicMock()
        request.headers = {}
        request.cookies = {"session_id": "admin-sid"}
        db = MagicMock()
        row = MagicMock()
        row.account_kind = "admin"
        row.market_is_admin = True
        db.query.return_value.filter.return_value.first.return_value = row

        assert mod._is_admin_customer_service_session(request, db) is True

    def test_non_admin_customer_service_session_reads_current_db(self):
        import app.fastapi_routes.im_routes as mod

        request = MagicMock()
        request.headers = {}
        request.cookies = {"session_id": "enterprise-sid"}
        db = MagicMock()
        row = MagicMock()
        row.account_kind = "enterprise"
        row.market_is_admin = False
        db.query.return_value.filter.return_value.first.return_value = row

        assert mod._is_admin_customer_service_session(request, db) is False

    def test_list_conversations(self, client):
        import app.fastapi_routes.im_routes as mod
        mod._schema_ready = True
        with patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls, \
             patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls:
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_conversations.return_value = []
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/im/conversations")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_admin_session_excludes_enterprise_dedicated_cs_from_conversations(self, client):
        import app.fastapi_routes.im_routes as mod
        mod._schema_ready = True
        with patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls, \
             patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls, \
             patch("app.fastapi_routes.im_routes._include_enterprise_dedicated_cs", return_value=False):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_conversations.return_value = []
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/im/conversations")
        assert resp.status_code == 200
        mock_svc.list_conversations.assert_called_once_with(
            1,
            include_enterprise_dedicated_cs=False,
        )

    def test_list_contacts(self, client):
        import app.fastapi_routes.im_routes as mod
        mod._schema_ready = True
        with patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls, \
             patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls:
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_contacts.return_value = []
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/im/contacts")
        assert resp.status_code == 200

    def test_admin_session_excludes_enterprise_dedicated_cs_from_contacts(self, client):
        import app.fastapi_routes.im_routes as mod
        mod._schema_ready = True
        with patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls, \
             patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls, \
             patch("app.fastapi_routes.im_routes._include_enterprise_dedicated_cs", return_value=False):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_contacts.return_value = []
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/im/contacts")
        assert resp.status_code == 200
        mock_svc.list_contacts.assert_called_once_with(
            1,
            include_enterprise_dedicated_cs=False,
        )

    def test_unread_total(self, client):
        import app.fastapi_routes.im_routes as mod
        mod._schema_ready = True
        with patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls, \
             patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls:
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_conversations.return_value = [{"unread_count": 3}, {"unread_count": 2}]
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/im/unread-total")
        assert resp.status_code == 200
        assert resp.json()["unread_total"] == 5

    def test_create_direct_invalid_peer(self, client):
        import app.fastapi_routes.im_routes as mod
        mod._schema_ready = True
        resp = client.post("/api/im/conversations/direct", json={"peer_user_id": 0})
        assert resp.status_code == 400

    def test_create_direct_same_user(self, client):
        import app.fastapi_routes.im_routes as mod
        mod._schema_ready = True
        with patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls, \
             patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls:
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.get_or_create_direct.side_effect = ValueError("不能与自己创建会话")
            mock_svc_cls.return_value = mock_svc
            resp = client.post("/api/im/conversations/direct", json={"peer_user_id": 1})
        assert resp.status_code == 400

    def test_codex_super_employee_rejects_non_admin_session(self, client):
        with patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls, \
             patch("app.fastapi_routes.im_routes._is_admin_customer_service_session", return_value=False):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            resp = client.post(
                "/api/admin/codex-super-employee/messages",
                json={"message": "修复登录问题"},
            )
        assert resp.status_code == 403

    def test_codex_super_employee_invokes_service_for_admin(self, client):
        service_result = {
            "employee": {"id": "codex-super-employee", "name": "超级员工-Codex"},
            "dispatch": {"request_id": "req-1", "status": "queued", "queued": True},
            "message": {"id": "m1", "role": "user", "body": "修复登录问题"},
            "assistant_message": {"id": "m2", "role": "assistant", "body": "已入队"},
            "messages": [],
        }
        with patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls, \
             patch("app.fastapi_routes.im_routes._is_admin_customer_service_session", return_value=True), \
             patch("app.fastapi_routes.im_routes.CodexSuperEmployeeService") as mock_svc_cls:
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.invoke.return_value = service_result
            mock_svc_cls.return_value = mock_svc
            resp = client.post(
                "/api/admin/codex-super-employee/messages",
                json={"message": "修复登录问题"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["dispatch"]["status"] == "queued"
        mock_svc.invoke.assert_called_once_with(
            user_id=1,
            message="修复登录问题",
            context={},
        )

    def test_codex_super_employee_lists_messages_for_admin(self, client):
        with patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls, \
             patch("app.fastapi_routes.im_routes._is_admin_customer_service_session", return_value=True), \
             patch("app.fastapi_routes.im_routes.CodexSuperEmployeeService") as mock_svc_cls:
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_messages.return_value = [{"id": "m1", "role": "assistant", "body": "ready"}]
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/admin/codex-super-employee/messages")
        assert resp.status_code == 200
        assert resp.json()["messages"][0]["body"] == "ready"
        mock_svc.list_messages.assert_called_once_with(user_id=1, limit=80)
