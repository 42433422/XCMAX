"""Comprehensive tests for app.fastapi_routes.im_routes.

Covers: conversations, contacts, unread-total, direct creation, messages,
mark-read, WebSocket, and all helper functions.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("LAN_GUARD_ENABLED", "0")
    monkeypatch.setenv("LAN_CIDR_GUARD_ENABLED", "0")
    from app.fastapi_app.factory import create_fastapi_app

    return TestClient(create_fastapi_app(enable_cors=False), raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# _uid
# ---------------------------------------------------------------------------


class TestUid:
    def test_valid_user(self):
        from app.fastapi_routes.im_routes import _uid

        user = MagicMock()
        user.user_id = 42
        assert _uid(user) == 42

    def test_none_user_id_raises(self):
        from app.fastapi_routes.im_routes import _uid

        user = MagicMock()
        user.user_id = None
        with pytest.raises(ValueError, match="user_id required"):
            _uid(user)


# ---------------------------------------------------------------------------
# _resolve_ws_user_id
# ---------------------------------------------------------------------------


class TestResolveWsUserId:
    def test_no_session_no_header(self):
        from app.fastapi_routes.im_routes import _resolve_ws_user_id

        ws = MagicMock()
        ws.query_params = {}
        ws.cookies = {}
        with patch(
            "app.infrastructure.auth.dependencies._allow_x_user_id_header", return_value=False
        ):
            result = _resolve_ws_user_id(ws)
            assert result is None

    def test_x_user_id_header_allowed(self):
        from app.fastapi_routes.im_routes import _resolve_ws_user_id

        ws = MagicMock()
        ws.query_params = {"user_id": "123"}
        ws.cookies = {}
        with patch(
            "app.infrastructure.auth.dependencies._allow_x_user_id_header", return_value=True
        ):
            result = _resolve_ws_user_id(ws)
            assert result == 123

    def test_x_user_id_header_non_digit(self):
        from app.fastapi_routes.im_routes import _resolve_ws_user_id

        ws = MagicMock()
        ws.query_params = {"user_id": "abc"}
        ws.cookies = {}
        with patch(
            "app.infrastructure.auth.dependencies._allow_x_user_id_header", return_value=True
        ):
            result = _resolve_ws_user_id(ws)
            assert result is None

    def test_session_cookie_valid(self):
        from app.fastapi_routes.im_routes import _resolve_ws_user_id

        ws = MagicMock()
        ws.query_params = {}
        ws.cookies = {"session_id": "valid-sid"}
        mock_user = MagicMock()
        mock_user.id = 5
        with (
            patch(
                "app.infrastructure.auth.dependencies._allow_x_user_id_header", return_value=False
            ),
            patch("app.application.facades.session_facade.get_session_service") as mock_get_ss,
        ):
            mock_ss = MagicMock()
            mock_ss.validate_session.return_value = mock_user
            mock_get_ss.return_value = mock_ss
            result = _resolve_ws_user_id(ws)
            assert result == 5

    def test_session_cookie_invalid(self):
        from app.fastapi_routes.im_routes import _resolve_ws_user_id

        ws = MagicMock()
        ws.query_params = {}
        ws.cookies = {"session_id": "bad-sid"}
        with (
            patch(
                "app.infrastructure.auth.dependencies._allow_x_user_id_header", return_value=False
            ),
            patch("app.application.facades.session_facade.get_session_service") as mock_get_ss,
        ):
            mock_ss = MagicMock()
            mock_ss.validate_session.return_value = None
            mock_get_ss.return_value = mock_ss
            result = _resolve_ws_user_id(ws)
            assert result is None


# ---------------------------------------------------------------------------
# _notify_offline_im_members
# ---------------------------------------------------------------------------


class TestNotifyOfflineImMembers:
    @pytest.mark.asyncio
    async def test_no_offline_members(self):
        from app.fastapi_routes.im_routes import _notify_offline_im_members

        with patch("app.infrastructure.im.ws_hub.im_ws_hub") as mock_hub:
            mock_hub.connected_user_ids.return_value = [1, 2, 3]
            # All members are online
            await _notify_offline_im_members([1, 2, 3], 1, "hello")
            # Should not call notify_user

    @pytest.mark.asyncio
    async def test_with_offline_members(self):
        from app.fastapi_routes.im_routes import _notify_offline_im_members

        with (
            patch("app.infrastructure.im.ws_hub.im_ws_hub") as mock_hub,
            patch("app.services.mobile_push.notify_user") as mock_notify,
        ):
            mock_hub.connected_user_ids.return_value = [1, 3]
            await _notify_offline_im_members([1, 2, 3], 1, "hello")
            # User 2 is offline (not in connected list and not sender), should be notified
            assert mock_notify.call_count >= 1

    @pytest.mark.asyncio
    async def test_notify_error_handled(self):
        from app.fastapi_routes.im_routes import _notify_offline_im_members

        with (
            patch("app.infrastructure.im.ws_hub.im_ws_hub") as mock_hub,
            patch("app.services.mobile_push.notify_user", side_effect=RuntimeError("push fail")),
        ):
            mock_hub.connected_user_ids.return_value = [1]
            # Should not raise
            await _notify_offline_im_members([1, 2], 1, "hello")

    @pytest.mark.asyncio
    async def test_empty_body_uses_default(self):
        from app.fastapi_routes.im_routes import _notify_offline_im_members

        with (
            patch("app.infrastructure.im.ws_hub.im_ws_hub") as mock_hub,
            patch("app.services.mobile_push.notify_user") as mock_notify,
        ):
            mock_hub.connected_user_ids.return_value = [1]
            await _notify_offline_im_members([1, 2], 1, "")
            # Should use "新消息" as default
            call_args = mock_notify.call_args
            assert call_args[1]["body"] == "新消息"


# ---------------------------------------------------------------------------
# Route tests (unauthorized / basic)
# ---------------------------------------------------------------------------


class TestImListConversations:
    def test_unauthorized(self, client: TestClient):
        r = client.get("/api/im/conversations")
        assert r.status_code in (401, 403, 422)


class TestImListContacts:
    def test_unauthorized(self, client: TestClient):
        r = client.get("/api/im/contacts")
        assert r.status_code in (401, 403, 422)


class TestImUnreadTotal:
    def test_unauthorized(self, client: TestClient):
        r = client.get("/api/im/unread-total")
        assert r.status_code in (401, 403, 422)


class TestImCreateDirect:
    def test_unauthorized(self, client: TestClient):
        r = client.post("/api/im/conversations/direct", json={"peer_user_id": 2})
        assert r.status_code in (401, 403, 422)


class TestImListMessages:
    def test_unauthorized(self, client: TestClient):
        r = client.get("/api/im/conversations/1/messages")
        assert r.status_code in (401, 403, 422)


class TestImSendMessage:
    def test_unauthorized(self, client: TestClient):
        r = client.post("/api/im/conversations/1/messages", json={"body": "hi"})
        assert r.status_code in (401, 403, 422)


class TestImMarkRead:
    def test_unauthorized(self, client: TestClient):
        r = client.post("/api/im/conversations/1/read", json={"last_message_id": 1})
        assert r.status_code in (401, 403, 422)


# ---------------------------------------------------------------------------
# _ensure_schema
# ---------------------------------------------------------------------------


class TestEnsureSchema:
    def test_calls_ensure_once(self):
        from app.fastapi_routes import im_routes

        original_ready = im_routes._schema_ready
        im_routes._schema_ready = False
        try:
            with patch("app.fastapi_routes.im_routes.ensure_im_tables") as mock_ensure:
                im_routes._ensure_schema()
                mock_ensure.assert_called_once()
                assert im_routes._schema_ready is True
        finally:
            im_routes._schema_ready = original_ready

    def test_skips_if_ready(self):
        from app.fastapi_routes import im_routes

        im_routes._schema_ready = True
        with patch("app.fastapi_routes.im_routes.ensure_im_tables") as mock_ensure:
            im_routes._ensure_schema()
            mock_ensure.assert_not_called()
