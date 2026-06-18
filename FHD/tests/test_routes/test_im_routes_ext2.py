"""Tests for app.fastapi_routes.im_routes — coverage ramp."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.fastapi_routes.im_routes import (
    _ensure_schema,
    _notify_offline_im_members,
    _resolve_ws_user_id,
    _uid,
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
        with (
            patch("app.fastapi_routes.im_routes.ensure_im_tables") as mock_ensure,
            patch("app.fastapi_routes.im_routes.get_host_engine", return_value=MagicMock()),
        ):
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
        with (
            patch(
                "app.infrastructure.auth.dependencies._allow_x_user_id_header", return_value=False
            ),
            patch("app.fastapi_routes.im_routes.Config", SESSION_COOKIE_NAME="session_id"),
        ):
            result = _resolve_ws_user_id(ws)
        assert result is None

    def test_returns_uid_from_query_param(self):
        ws = MagicMock()
        ws.query_params = {"user_id": "42", "session_id": ""}
        ws.cookies = {}
        with patch(
            "app.infrastructure.auth.dependencies._allow_x_user_id_header", return_value=True
        ):
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
        with (
            patch(
                "app.infrastructure.auth.dependencies._allow_x_user_id_header", return_value=False
            ),
            patch("app.fastapi_routes.im_routes.Config", SESSION_COOKIE_NAME="session_id"),
            patch(
                "app.application.facades.session_facade.get_session_service",
                return_value=mock_session_svc,
            ),
        ):
            result = _resolve_ws_user_id(ws)
        assert result == 7

    def test_returns_none_when_session_invalid(self):
        ws = MagicMock()
        ws.query_params = {"user_id": "", "session_id": "bad"}
        ws.cookies = {"session_id": "bad"}
        mock_session_svc = MagicMock()
        mock_session_svc.validate_session.return_value = None
        with (
            patch(
                "app.infrastructure.auth.dependencies._allow_x_user_id_header", return_value=False
            ),
            patch("app.fastapi_routes.im_routes.Config", SESSION_COOKIE_NAME="session_id"),
            patch(
                "app.application.facades.session_facade.get_session_service",
                return_value=mock_session_svc,
            ),
        ):
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
        with (
            patch("app.fastapi_routes.im_routes.im_ws_hub") as mock_hub,
            patch("app.services.mobile_push.notify_user") as mock_notify,
        ):
            mock_hub.connected_user_ids.return_value = [1]
            await _notify_offline_im_members([1, 2, 3], 1, "hello")
            assert mock_notify.call_count == 2

    @pytest.mark.asyncio
    async def test_push_error_does_not_crash(self):
        with (
            patch("app.fastapi_routes.im_routes.im_ws_hub") as mock_hub,
            patch("app.services.mobile_push.notify_user", side_effect=RuntimeError("push fail")),
        ):
            mock_hub.connected_user_ids.return_value = [1]
            await _notify_offline_im_members([1, 2], 1, "hello")
        # Should not raise

    @pytest.mark.asyncio
    async def test_import_error_skips_push(self):
        with (
            patch("app.fastapi_routes.im_routes.im_ws_hub") as mock_hub,
            patch("app.services.mobile_push.notify_user", side_effect=ImportError("no module")),
        ):
            mock_hub.connected_user_ids.return_value = [1]
            await _notify_offline_im_members([1, 2], 1, "hello")
        # Should not raise


# ---------------------------------------------------------------------------
# Route handler tests (using TestClient)
# ---------------------------------------------------------------------------


class TestImRoutes:
    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.infrastructure.auth.dependencies import require_identified_user

        app = FastAPI()
        app.include_router(router)
        mock_user = MagicMock()
        mock_user.user_id = 1
        app.dependency_overrides[require_identified_user] = lambda: mock_user
        return TestClient(app)

    def test_list_conversations(self, client):
        import app.fastapi_routes.im_routes as mod

        mod._schema_ready = True
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_conversations.return_value = []
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/im/conversations")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_list_contacts(self, client):
        import app.fastapi_routes.im_routes as mod

        mod._schema_ready = True
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_contacts.return_value = []
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/im/contacts")
        assert resp.status_code == 200

    def test_unread_total(self, client):
        import app.fastapi_routes.im_routes as mod

        mod._schema_ready = True
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
        ):
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
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.get_or_create_direct.side_effect = ValueError("不能与自己创建会话")
            mock_svc_cls.return_value = mock_svc
            resp = client.post("/api/im/conversations/direct", json={"peer_user_id": 1})
        assert resp.status_code == 400
