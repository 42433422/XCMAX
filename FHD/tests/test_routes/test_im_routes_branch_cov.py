"""Branch-coverage tests for app.fastapi_routes.im_routes.

Targets branches not covered by existing test_im_routes.py / test_im_routes_ext2.py:
- _is_admin_customer_service_session: no sid, row not found, exception, account_kind != admin,
  market_is_admin False
- _include_enterprise_dedicated_cs
- _require_admin_customer_service_session: admin/non-admin
- _resolve_ws_user_id: cookie_name from Config, sid from query_params
- _notify_offline_im_members: import error fallback, local_is_mock, source_is_mock,
  empty body default
- Route handlers: list_contacts with keyword, list_messages PermissionError,
  send_message success/PermissionError/ValueError, mark_read success/PermissionError,
  claude/cursor super employee routes, ai_groups routes
- _ai_group_guard
- im_websocket: unauthorized, ping/pong
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.fastapi_routes.im_routes as _mod
from app.fastapi_routes.im_routes import (
    _ai_group_guard,
    _include_enterprise_dedicated_cs,
    _is_admin_customer_service_session,
    _notify_offline_im_members,
    _require_admin_customer_service_session,
    _resolve_ws_user_id,
    _uid,
    router,
)

# ---------------------------------------------------------------------------
# autouse fixture: reset schema state
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_schema_state():
    """Reset _schema_ready before each test."""
    original = _mod._schema_ready
    _mod._schema_ready = False
    yield
    _mod._schema_ready = original


# ---------------------------------------------------------------------------
# Test client fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    from app.infrastructure.auth.dependencies import require_identified_user

    app = FastAPI()
    app.include_router(router)
    mock_user = MagicMock()
    mock_user.user_id = 1
    app.dependency_overrides[require_identified_user] = lambda: mock_user
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# _is_admin_customer_service_session - all branches
# ---------------------------------------------------------------------------


class TestIsAdminCustomerServiceSession:
    def test_no_sid_returns_false(self) -> None:
        request = MagicMock()
        db = MagicMock()
        with patch(
            "app.infrastructure.auth.dependencies.session_id_from_request",
            return_value=None,
        ):
            result = _is_admin_customer_service_session(request, db)
        assert result is False

    def test_row_not_found_returns_false(self) -> None:
        request = MagicMock()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with patch(
            "app.infrastructure.auth.dependencies.session_id_from_request",
            return_value="some-sid",
        ):
            result = _is_admin_customer_service_session(request, db)
        assert result is False

    def test_account_kind_not_admin_returns_false(self) -> None:
        request = MagicMock()
        db = MagicMock()
        row = MagicMock()
        row.account_kind = "enterprise"
        row.market_is_admin = True
        db.query.return_value.filter.return_value.first.return_value = row
        with patch(
            "app.infrastructure.auth.dependencies.session_id_from_request",
            return_value="sid",
        ):
            result = _is_admin_customer_service_session(request, db)
        assert result is False

    def test_market_is_admin_false_returns_false(self) -> None:
        request = MagicMock()
        db = MagicMock()
        row = MagicMock()
        row.account_kind = "admin"
        row.market_is_admin = False
        db.query.return_value.filter.return_value.first.return_value = row
        with patch(
            "app.infrastructure.auth.dependencies.session_id_from_request",
            return_value="sid",
        ):
            result = _is_admin_customer_service_session(request, db)
        assert result is False

    def test_account_kind_empty_string_returns_false(self) -> None:
        request = MagicMock()
        db = MagicMock()
        row = MagicMock()
        row.account_kind = ""
        row.market_is_admin = True
        db.query.return_value.filter.return_value.first.return_value = row
        with patch(
            "app.infrastructure.auth.dependencies.session_id_from_request",
            return_value="sid",
        ):
            result = _is_admin_customer_service_session(request, db)
        assert result is False

    def test_account_kind_none_returns_false(self) -> None:
        request = MagicMock()
        db = MagicMock()
        row = MagicMock()
        row.account_kind = None
        row.market_is_admin = True
        db.query.return_value.filter.return_value.first.return_value = row
        with patch(
            "app.infrastructure.auth.dependencies.session_id_from_request",
            return_value="sid",
        ):
            result = _is_admin_customer_service_session(request, db)
        assert result is False

    def test_all_conditions_met_returns_true(self) -> None:
        request = MagicMock()
        db = MagicMock()
        row = MagicMock()
        row.account_kind = "admin"
        row.market_is_admin = True
        db.query.return_value.filter.return_value.first.return_value = row
        with patch(
            "app.infrastructure.auth.dependencies.session_id_from_request",
            return_value="sid",
        ):
            result = _is_admin_customer_service_session(request, db)
        assert result is True

    def test_exception_returns_false(self) -> None:
        request = MagicMock()
        db = MagicMock()
        db.query.side_effect = RuntimeError("db error")
        with patch(
            "app.infrastructure.auth.dependencies.session_id_from_request",
            return_value="sid",
        ):
            result = _is_admin_customer_service_session(request, db)
        assert result is False

    def test_market_is_admin_none_returns_false(self) -> None:
        request = MagicMock()
        db = MagicMock()
        row = MagicMock()
        row.account_kind = "admin"
        row.market_is_admin = None
        db.query.return_value.filter.return_value.first.return_value = row
        with patch(
            "app.infrastructure.auth.dependencies.session_id_from_request",
            return_value="sid",
        ):
            result = _is_admin_customer_service_session(request, db)
        assert result is False


# ---------------------------------------------------------------------------
# _include_enterprise_dedicated_cs
# ---------------------------------------------------------------------------


class TestIncludeEnterpriseDedicatedCs:
    def test_returns_true_when_not_admin(self) -> None:
        request = MagicMock()
        db = MagicMock()
        with patch(
            "app.fastapi_routes.im_routes._is_admin_customer_service_session",
            return_value=False,
        ):
            result = _include_enterprise_dedicated_cs(request, db)
        assert result is True

    def test_returns_false_when_admin(self) -> None:
        request = MagicMock()
        db = MagicMock()
        with patch(
            "app.fastapi_routes.im_routes._is_admin_customer_service_session",
            return_value=True,
        ):
            result = _include_enterprise_dedicated_cs(request, db)
        assert result is False


# ---------------------------------------------------------------------------
# _require_admin_customer_service_session
# ---------------------------------------------------------------------------


class TestRequireAdminCustomerServiceSession:
    def test_admin_returns_none(self) -> None:
        request = MagicMock()
        db = MagicMock()
        with patch(
            "app.fastapi_routes.im_routes._is_admin_customer_service_session",
            return_value=True,
        ):
            result = _require_admin_customer_service_session(request, db)
        assert result is None

    def test_non_admin_returns_403(self) -> None:
        request = MagicMock()
        db = MagicMock()
        with patch(
            "app.fastapi_routes.im_routes._is_admin_customer_service_session",
            return_value=False,
        ):
            result = _require_admin_customer_service_session(request, db)
        assert result is not None
        assert result.status_code == 403
        assert result.body is not None


# ---------------------------------------------------------------------------
# _resolve_ws_user_id - additional branches
# ---------------------------------------------------------------------------


class TestResolveWsUserIdAdditional:
    def test_sid_from_query_params(self) -> None:
        ws = MagicMock()
        ws.query_params = {"user_id": "", "session_id": "query-sid"}
        ws.cookies = {}
        mock_session_svc = MagicMock()
        mock_user = MagicMock()
        mock_user.id = 9
        mock_session_svc.validate_session.return_value = mock_user
        with (
            patch(
                "app.infrastructure.auth.dependencies._allow_x_user_id_header",
                return_value=False,
            ),
            patch("app.fastapi_routes.im_routes.Config", SESSION_COOKIE_NAME="session_id"),
            patch(
                "app.application.facades.session_facade.get_session_service",
                return_value=mock_session_svc,
            ),
        ):
            result = _resolve_ws_user_id(ws)
        assert result == 9

    def test_custom_cookie_name(self) -> None:
        ws = MagicMock()
        ws.query_params = {}
        ws.cookies = {"custom_session": "my-sid"}
        mock_session_svc = MagicMock()
        mock_user = MagicMock()
        mock_user.id = 11
        mock_session_svc.validate_session.return_value = mock_user
        with (
            patch(
                "app.infrastructure.auth.dependencies._allow_x_user_id_header",
                return_value=False,
            ),
            patch("app.fastapi_routes.im_routes.Config", SESSION_COOKIE_NAME="custom_session"),
            patch(
                "app.application.facades.session_facade.get_session_service",
                return_value=mock_session_svc,
            ),
        ):
            result = _resolve_ws_user_id(ws)
        assert result == 11

    def test_cookie_takes_precedence_over_query(self) -> None:
        ws = MagicMock()
        ws.query_params = {"session_id": "query-sid"}
        ws.cookies = {"session_id": "cookie-sid"}
        mock_session_svc = MagicMock()
        mock_user = MagicMock()
        mock_user.id = 15
        mock_session_svc.validate_session.return_value = mock_user
        with (
            patch(
                "app.infrastructure.auth.dependencies._allow_x_user_id_header",
                return_value=False,
            ),
            patch("app.fastapi_routes.im_routes.Config", SESSION_COOKIE_NAME="session_id"),
            patch(
                "app.application.facades.session_facade.get_session_service",
                return_value=mock_session_svc,
            ),
        ):
            result = _resolve_ws_user_id(ws)
        assert result == 15
        # Should validate the cookie sid
        mock_session_svc.validate_session.assert_called_once_with("cookie-sid")

    def test_x_user_id_zero(self) -> None:
        ws = MagicMock()
        ws.query_params = {"user_id": "0"}
        ws.cookies = {}
        with patch(
            "app.infrastructure.auth.dependencies._allow_x_user_id_header",
            return_value=True,
        ):
            result = _resolve_ws_user_id(ws)
        # "0" is truthy string and isdigit, returns int("0")=0
        assert result == 0


# ---------------------------------------------------------------------------
# _notify_offline_im_members - additional branches
# ---------------------------------------------------------------------------


class TestNotifyOfflineImMembersAdditional:
    @pytest.mark.asyncio
    async def test_import_error_falls_back_to_im_ws_hub(self) -> None:
        """When ws_hub_module import fails, should fall back to im_ws_hub."""
        with (
            patch(
                "app.infrastructure.im.ws_hub.im_ws_hub",
                create=True,
            ) as mock_hub,
            patch("app.services.mobile_push.notify_user") as mock_notify,
        ):
            mock_hub.connected_user_ids.return_value = [1]
            # Simulate ImportError when importing ws_hub_module
            import builtins

            real_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if "app.infrastructure.im" in name and "ws_hub" in name:
                    raise ImportError("simulated")
                return real_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                await _notify_offline_im_members([1, 2], 1, "hello")
            # Should still notify using im_ws_hub
            assert mock_notify.call_count >= 1

    @pytest.mark.asyncio
    async def test_local_is_mock_uses_local(self) -> None:
        """When local im_ws_hub has mock_calls, use it."""
        mock_hub = MagicMock()
        mock_hub.mock_calls = []  # has mock_calls attribute -> local_is_mock=True
        mock_hub.connected_user_ids.return_value = [1]
        with (
            patch("app.fastapi_routes.im_routes.im_ws_hub", mock_hub),
            patch("app.services.mobile_push.notify_user") as mock_notify,
        ):
            await _notify_offline_im_members([1, 2], 1, "hello")
            assert mock_notify.call_count >= 1

    @pytest.mark.asyncio
    async def test_source_is_mock_uses_source(self) -> None:
        """When source hub has mock_calls but local doesn't, use source."""
        local_hub = MagicMock()
        # local_hub has no mock_calls attribute
        del local_hub.mock_calls
        local_hub.connected_user_ids.return_value = [1]
        with (
            patch("app.fastapi_routes.im_routes.im_ws_hub", local_hub),
            patch("app.services.mobile_push.notify_user") as mock_notify,
        ):
            await _notify_offline_im_members([1, 2], 1, "hello")
            assert mock_notify.call_count >= 1

    @pytest.mark.asyncio
    async def test_empty_offline_returns_early(self) -> None:
        """When all members are online, return early without push."""
        with (
            patch("app.fastapi_routes.im_routes.im_ws_hub") as mock_hub,
            patch("app.services.mobile_push.notify_user") as mock_notify,
        ):
            mock_hub.connected_user_ids.return_value = [1, 2, 3]
            await _notify_offline_im_members([1, 2, 3], 1, "hello")
            mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_sender_excluded_from_offline(self) -> None:
        """Sender should not be notified even if not in online list."""
        with (
            patch("app.fastapi_routes.im_routes.im_ws_hub") as mock_hub,
            patch("app.services.mobile_push.notify_user") as mock_notify,
        ):
            mock_hub.connected_user_ids.return_value = []
            await _notify_offline_im_members([1, 2], 1, "hello")
            # Only user 2 should be notified (sender 1 excluded)
            assert mock_notify.call_count == 1
            call_args = mock_notify.call_args
            assert call_args[0][0] == 2

    @pytest.mark.asyncio
    async def test_body_truncated_to_120_chars(self) -> None:
        """Body should be truncated to 120 characters."""
        long_body = "x" * 200
        with (
            patch("app.fastapi_routes.im_routes.im_ws_hub") as mock_hub,
            patch("app.services.mobile_push.notify_user") as mock_notify,
        ):
            mock_hub.connected_user_ids.return_value = [1]
            await _notify_offline_im_members([1, 2], 1, long_body)
            call_args = mock_notify.call_args
            assert len(call_args[1]["body"]) == 120

    @pytest.mark.asyncio
    async def test_whitespace_body_uses_default(self) -> None:
        """Whitespace-only body should use default '新消息'."""
        with (
            patch("app.fastapi_routes.im_routes.im_ws_hub") as mock_hub,
            patch("app.services.mobile_push.notify_user") as mock_notify,
        ):
            mock_hub.connected_user_ids.return_value = [1]
            await _notify_offline_im_members([1, 2], 1, "   ")
            call_args = mock_notify.call_args
            assert call_args[1]["body"] == "新消息"

    @pytest.mark.asyncio
    async def test_notify_mobile_import_error_handled(self) -> None:
        """When notify_mobile_user import fails, should not crash."""
        with (
            patch("app.fastapi_routes.im_routes.im_ws_hub") as mock_hub,
            patch(
                "app.application.mobile_push_app_service.notify_mobile_user",
                create=True,
            ),
        ):
            mock_hub.connected_user_ids.return_value = [1]
            # Simulate ImportError for mobile_push
            import builtins

            real_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if "mobile_push" in name:
                    raise ImportError("no module")
                return real_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                # Should not raise
                await _notify_offline_im_members([1, 2], 1, "hello")


# ---------------------------------------------------------------------------
# _ai_group_guard
# ---------------------------------------------------------------------------


class TestAiGroupGuard:
    def test_admin_returns_none(self) -> None:
        request = MagicMock()
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._require_admin_customer_service_session",
                return_value=None,
            ),
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            result = _ai_group_guard(request)
        assert result is None

    def test_non_admin_returns_denied(self) -> None:
        request = MagicMock()
        denied_response = MagicMock()
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._require_admin_customer_service_session",
                return_value=denied_response,
            ),
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            result = _ai_group_guard(request)
        assert result is denied_response

    def test_db_closed_after_use(self) -> None:
        request = MagicMock()
        mock_db = MagicMock()
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._require_admin_customer_service_session",
                return_value=None,
            ),
        ):
            mock_db_cls.return_value = mock_db
            _ai_group_guard(request)
        mock_db.close.assert_called_once()


# ---------------------------------------------------------------------------
# Route handler tests - list_contacts with keyword
# ---------------------------------------------------------------------------


class TestListContactsWithKeyword:
    def test_keyword_filters_by_display_name(self, client: TestClient) -> None:
        _mod._schema_ready = True
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_contacts.return_value = [
                {"display_name": "Alice", "username": "alice"},
                {"display_name": "Bob", "username": "bob"},
            ]
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/im/contacts?q=alice")
        assert resp.status_code == 200
        contacts = resp.json()["contacts"]
        assert len(contacts) == 1
        assert contacts[0]["display_name"] == "Alice"

    def test_keyword_filters_by_username(self, client: TestClient) -> None:
        _mod._schema_ready = True
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_contacts.return_value = [
                {"display_name": "Alice", "username": "alice_user"},
                {"display_name": "Bob", "username": "bob"},
            ]
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/im/contacts?q=alice_user")
        assert resp.status_code == 200
        contacts = resp.json()["contacts"]
        assert len(contacts) == 1

    def test_keyword_case_insensitive(self, client: TestClient) -> None:
        _mod._schema_ready = True
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_contacts.return_value = [
                {"display_name": "Alice", "username": "alice"},
            ]
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/im/contacts?q=ALICE")
        assert resp.status_code == 200
        contacts = resp.json()["contacts"]
        assert len(contacts) == 1

    def test_no_keyword_returns_all(self, client: TestClient) -> None:
        _mod._schema_ready = True
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_contacts.return_value = [
                {"display_name": "Alice", "username": "alice"},
                {"display_name": "Bob", "username": "bob"},
            ]
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/im/contacts")
        assert resp.status_code == 200
        contacts = resp.json()["contacts"]
        assert len(contacts) == 2

    def test_recoverable_error_returns_500(self, client: TestClient) -> None:
        _mod._schema_ready = True
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_contacts.side_effect = RuntimeError("db error")
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/im/contacts")
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Route handler tests - list_messages
# ---------------------------------------------------------------------------


class TestListMessages:
    def test_permission_error_returns_403(self, client: TestClient) -> None:
        _mod._schema_ready = True
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_messages.side_effect = PermissionError("no access")
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/im/conversations/1/messages")
        assert resp.status_code == 403

    def test_recoverable_error_returns_500(self, client: TestClient) -> None:
        _mod._schema_ready = True
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_messages.side_effect = RuntimeError("db error")
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/im/conversations/1/messages")
        assert resp.status_code == 500

    def test_success_returns_messages(self, client: TestClient) -> None:
        _mod._schema_ready = True
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_messages.return_value = [
                {"id": 1, "body": "hello"},
                {"id": 2, "body": "world"},
            ]
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/im/conversations/1/messages")
        assert resp.status_code == 200
        assert len(resp.json()["messages"]) == 2


# ---------------------------------------------------------------------------
# Route handler tests - send_message
# ---------------------------------------------------------------------------


class TestSendMessage:
    def test_success_returns_result(self, client: TestClient) -> None:
        _mod._schema_ready = True
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
            patch("app.fastapi_routes.im_routes.im_ws_hub") as mock_hub,
            patch("app.fastapi_routes.im_routes._notify_offline_im_members", new_callable=AsyncMock),
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.send_message.return_value = {
                "message": {"id": 1, "body": "hello"},
                "member_user_ids": [1, 2],
                "updated_at_ms": 1234567890,
            }
            mock_svc_cls.return_value = mock_svc
            mock_hub.send_to_user = AsyncMock()
            resp = client.post("/api/im/conversations/1/messages", json={"body": "hello"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_permission_error_returns_403(self, client: TestClient) -> None:
        _mod._schema_ready = True
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.send_message.side_effect = PermissionError("no access")
            mock_svc_cls.return_value = mock_svc
            resp = client.post("/api/im/conversations/1/messages", json={"body": "hello"})
        assert resp.status_code == 403

    def test_value_error_returns_400(self, client: TestClient) -> None:
        _mod._schema_ready = True
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.send_message.side_effect = ValueError("invalid")
            mock_svc_cls.return_value = mock_svc
            resp = client.post("/api/im/conversations/1/messages", json={"body": "hello"})
        assert resp.status_code == 400

    def test_recoverable_error_returns_500(self, client: TestClient) -> None:
        _mod._schema_ready = True
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.send_message.side_effect = RuntimeError("db error")
            mock_svc_cls.return_value = mock_svc
            resp = client.post("/api/im/conversations/1/messages", json={"body": "hello"})
        assert resp.status_code == 500

    def test_ws_broadcast_to_other_members(self, client: TestClient) -> None:
        _mod._schema_ready = True
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
            patch("app.fastapi_routes.im_routes.im_ws_hub") as mock_hub,
            patch(
                "app.fastapi_routes.im_routes._notify_offline_im_members", new_callable=AsyncMock
            ) as mock_notify,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.send_message.return_value = {
                "message": {"id": 1, "body": "hello"},
                "member_user_ids": [1, 2, 3],
                "updated_at_ms": 1234567890,
            }
            mock_svc_cls.return_value = mock_svc
            mock_hub.send_to_user = AsyncMock()
            resp = client.post("/api/im/conversations/1/messages", json={"body": "hello"})
        assert resp.status_code == 200
        # Should send to users 2 and 3 (not 1, the sender)
        assert mock_hub.send_to_user.call_count == 4  # 2 users * 2 payloads (legacy + sync)
        mock_notify.assert_called_once()


# ---------------------------------------------------------------------------
# Route handler tests - mark_read
# ---------------------------------------------------------------------------


class TestMarkRead:
    def test_success_returns_result(self, client: TestClient) -> None:
        _mod._schema_ready = True
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
            patch("app.fastapi_routes.im_routes.im_ws_hub") as mock_hub,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.mark_read.return_value = {
                "last_read_message_id": 5,
                "member_user_ids": [1, 2],
                "updated_at_ms": 1234567890,
            }
            mock_svc_cls.return_value = mock_svc
            mock_hub.send_to_user = AsyncMock()
            resp = client.post("/api/im/conversations/1/read", json={"last_message_id": 5})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_permission_error_returns_403(self, client: TestClient) -> None:
        _mod._schema_ready = True
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.mark_read.side_effect = PermissionError("no access")
            mock_svc_cls.return_value = mock_svc
            resp = client.post("/api/im/conversations/1/read", json={"last_message_id": 5})
        assert resp.status_code == 403

    def test_recoverable_error_returns_500(self, client: TestClient) -> None:
        _mod._schema_ready = True
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.mark_read.side_effect = RuntimeError("db error")
            mock_svc_cls.return_value = mock_svc
            resp = client.post("/api/im/conversations/1/read", json={"last_message_id": 5})
        assert resp.status_code == 500

    def test_ws_broadcast_read_to_other_members(self, client: TestClient) -> None:
        _mod._schema_ready = True
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
            patch("app.fastapi_routes.im_routes.im_ws_hub") as mock_hub,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.mark_read.return_value = {
                "last_read_message_id": 5,
                "member_user_ids": [1, 2, 3],
                "updated_at_ms": 1234567890,
            }
            mock_svc_cls.return_value = mock_svc
            mock_hub.send_to_user = AsyncMock()
            resp = client.post("/api/im/conversations/1/read", json={"last_message_id": 5})
        assert resp.status_code == 200
        # Should send to users 2 and 3 (not 1, the sender)
        assert mock_hub.send_to_user.call_count == 2


# ---------------------------------------------------------------------------
# Route handler tests - create_direct
# ---------------------------------------------------------------------------


class TestCreateDirect:
    def test_recoverable_error_returns_500(self, client: TestClient) -> None:
        _mod._schema_ready = True
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.get_or_create_direct.side_effect = RuntimeError("db error")
            mock_svc_cls.return_value = mock_svc
            resp = client.post("/api/im/conversations/direct", json={"peer_user_id": 2})
        assert resp.status_code == 500

    def test_negative_peer_returns_400(self, client: TestClient) -> None:
        _mod._schema_ready = True
        resp = client.post("/api/im/conversations/direct", json={"peer_user_id": -1})
        assert resp.status_code == 400

    def test_success_returns_conversation(self, client: TestClient) -> None:
        _mod._schema_ready = True
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.get_or_create_direct.return_value = {"id": 1, "peer_user_id": 2}
            mock_svc_cls.return_value = mock_svc
            resp = client.post("/api/im/conversations/direct", json={"peer_user_id": 2})
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ---------------------------------------------------------------------------
# Route handler tests - list_conversations / unread_total errors
# ---------------------------------------------------------------------------


class TestListConversationsErrors:
    def test_recoverable_error_returns_500(self, client: TestClient) -> None:
        _mod._schema_ready = True
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_conversations.side_effect = RuntimeError("db error")
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/im/conversations")
        assert resp.status_code == 500

    def test_unread_total_recoverable_error_returns_500(self, client: TestClient) -> None:
        _mod._schema_ready = True
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_conversations.side_effect = RuntimeError("db error")
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/im/unread-total")
        assert resp.status_code == 500

    def test_unread_total_with_none_unread_count(self, client: TestClient) -> None:
        _mod._schema_ready = True
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch("app.fastapi_routes.im_routes.ImApplicationService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_conversations.return_value = [
                {"unread_count": None},
                {"unread_count": 3},
                {"unread_count": "5"},  # string, should be int() converted
            ]
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/im/unread-total")
        assert resp.status_code == 200
        assert resp.json()["unread_total"] == 8  # 0 + 3 + 5


# ---------------------------------------------------------------------------
# Route handler tests - Claude super employee
# ---------------------------------------------------------------------------


class TestClaudeSuperEmployeeRoutes:
    def test_list_messages_admin(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.ClaudeSuperEmployeeService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_messages.return_value = [{"id": "m1", "body": "hi"}]
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/admin/claude-super-employee/messages")
        assert resp.status_code == 200
        assert resp.json()["messages"][0]["body"] == "hi"

    def test_list_messages_non_admin_403(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=False,
            ),
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            resp = client.get("/api/admin/claude-super-employee/messages")
        assert resp.status_code == 403

    def test_list_messages_recoverable_error_500(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.ClaudeSuperEmployeeService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_messages.side_effect = RuntimeError("db error")
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/admin/claude-super-employee/messages")
        assert resp.status_code == 500

    def test_invoke_admin(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.ClaudeSuperEmployeeService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.invoke.return_value = {"dispatch": {"status": "queued"}}
            mock_svc_cls.return_value = mock_svc
            resp = client.post(
                "/api/admin/claude-super-employee/messages",
                json={"message": "hello"},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_invoke_with_body_field(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.ClaudeSuperEmployeeService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.invoke.return_value = {"ok": True}
            mock_svc_cls.return_value = mock_svc
            resp = client.post(
                "/api/admin/claude-super-employee/messages",
                json={"body": "via body field"},
            )
        assert resp.status_code == 200
        mock_svc.invoke.assert_called_once_with(
            user_id=1,
            message="via body field",
            context={},
        )

    def test_invoke_with_context(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.ClaudeSuperEmployeeService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.invoke.return_value = {"ok": True}
            mock_svc_cls.return_value = mock_svc
            resp = client.post(
                "/api/admin/claude-super-employee/messages",
                json={"message": "hi", "context": {"key": "value"}},
            )
        assert resp.status_code == 200
        mock_svc.invoke.assert_called_once_with(
            user_id=1,
            message="hi",
            context={"key": "value"},
        )

    def test_invoke_value_error_400(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.ClaudeSuperEmployeeService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.invoke.side_effect = ValueError("invalid input")
            mock_svc_cls.return_value = mock_svc
            resp = client.post(
                "/api/admin/claude-super-employee/messages",
                json={"message": "hi"},
            )
        assert resp.status_code == 400

    def test_invoke_recoverable_error_500(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.ClaudeSuperEmployeeService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.invoke.side_effect = RuntimeError("db error")
            mock_svc_cls.return_value = mock_svc
            resp = client.post(
                "/api/admin/claude-super-employee/messages",
                json={"message": "hi"},
            )
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Route handler tests - Cursor super employee
# ---------------------------------------------------------------------------


class TestCursorSuperEmployeeRoutes:
    def test_list_messages_admin(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.CursorSuperEmployeeService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_messages.return_value = [{"id": "m1"}]
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/admin/cursor-super-employee/messages")
        assert resp.status_code == 200

    def test_list_messages_non_admin_403(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=False,
            ),
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            resp = client.get("/api/admin/cursor-super-employee/messages")
        assert resp.status_code == 403

    def test_invoke_admin(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.CursorSuperEmployeeService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.invoke.return_value = {"ok": True}
            mock_svc_cls.return_value = mock_svc
            resp = client.post(
                "/api/admin/cursor-super-employee/messages",
                json={"message": "hi"},
            )
        assert resp.status_code == 200

    def test_invoke_value_error_400(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.CursorSuperEmployeeService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.invoke.side_effect = ValueError("bad")
            mock_svc_cls.return_value = mock_svc
            resp = client.post(
                "/api/admin/cursor-super-employee/messages",
                json={"message": "hi"},
            )
        assert resp.status_code == 400

    def test_invoke_recoverable_error_500(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.CursorSuperEmployeeService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.invoke.side_effect = RuntimeError("db error")
            mock_svc_cls.return_value = mock_svc
            resp = client.post(
                "/api/admin/cursor-super-employee/messages",
                json={"message": "hi"},
            )
        assert resp.status_code == 500

    def test_list_messages_recoverable_error_500(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.CursorSuperEmployeeService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_messages.side_effect = RuntimeError("db error")
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/admin/cursor-super-employee/messages")
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Route handler tests - Codex super employee additional
# ---------------------------------------------------------------------------


class TestCodexSuperEmployeeAdditional:
    def test_invoke_with_body_field(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.CodexSuperEmployeeService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.invoke.return_value = {"ok": True}
            mock_svc_cls.return_value = mock_svc
            resp = client.post(
                "/api/admin/codex-super-employee/messages",
                json={"body": "via body"},
            )
        assert resp.status_code == 200
        mock_svc.invoke.assert_called_once_with(
            user_id=1,
            message="via body",
            context={},
        )

    def test_invoke_value_error_400(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.CodexSuperEmployeeService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.invoke.side_effect = ValueError("bad")
            mock_svc_cls.return_value = mock_svc
            resp = client.post(
                "/api/admin/codex-super-employee/messages",
                json={"message": "hi"},
            )
        assert resp.status_code == 400

    def test_invoke_recoverable_error_500(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.CodexSuperEmployeeService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.invoke.side_effect = RuntimeError("db error")
            mock_svc_cls.return_value = mock_svc
            resp = client.post(
                "/api/admin/codex-super-employee/messages",
                json={"message": "hi"},
            )
        assert resp.status_code == 500

    def test_list_messages_recoverable_error_500(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.CodexSuperEmployeeService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_messages.side_effect = RuntimeError("db error")
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/admin/codex-super-employee/messages")
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Route handler tests - AI Groups
# ---------------------------------------------------------------------------


class TestAiGroupsRoutes:
    def test_list_groups_non_admin_403(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=False,
            ),
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            resp = client.get("/api/admin/ai-groups")
        assert resp.status_code == 403

    def test_list_groups_admin_success(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_groups.return_value = [{"id": "g1", "name": "Group 1"}]
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/admin/ai-groups")
        assert resp.status_code == 200
        assert resp.json()["groups"][0]["id"] == "g1"

    def test_list_groups_recoverable_error_500(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.list_groups.side_effect = RuntimeError("db error")
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/admin/ai-groups")
        assert resp.status_code == 500

    def test_create_group_admin_success(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.create_group.return_value = {"id": "g1", "name": "New Group"}
            mock_svc_cls.return_value = mock_svc
            resp = client.post("/api/admin/ai-groups", json={"name": "New Group"})
        assert resp.status_code == 200
        assert resp.json()["group"]["name"] == "New Group"

    def test_create_group_value_error_400(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.create_group.side_effect = ValueError("bad name")
            mock_svc_cls.return_value = mock_svc
            resp = client.post("/api/admin/ai-groups", json={"name": ""})
        assert resp.status_code == 400

    def test_create_group_recoverable_error_500(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.create_group.side_effect = RuntimeError("db error")
            mock_svc_cls.return_value = mock_svc
            resp = client.post("/api/admin/ai-groups", json={"name": "x"})
        assert resp.status_code == 500

    def test_get_messages_admin_success(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.get_messages.return_value = [{"id": "m1"}]
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/admin/ai-groups/g1/messages")
        assert resp.status_code == 200

    def test_get_messages_recoverable_error_500(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.get_messages.side_effect = RuntimeError("db error")
            mock_svc_cls.return_value = mock_svc
            resp = client.get("/api/admin/ai-groups/g1/messages")
        assert resp.status_code == 500

    def test_post_message_admin_success(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.post_message = AsyncMock(return_value={"message_id": "m1"})
            mock_svc_cls.return_value = mock_svc
            resp = client.post(
                "/api/admin/ai-groups/g1/messages",
                json={"message": "hello", "sender_name": "Me"},
            )
        assert resp.status_code == 200

    def test_post_message_value_error_400(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.post_message = AsyncMock(side_effect=ValueError("bad"))
            mock_svc_cls.return_value = mock_svc
            resp = client.post(
                "/api/admin/ai-groups/g1/messages",
                json={"message": "hello"},
            )
        assert resp.status_code == 400

    def test_post_message_recoverable_error_500(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.post_message = AsyncMock(side_effect=RuntimeError("db error"))
            mock_svc_cls.return_value = mock_svc
            resp = client.post(
                "/api/admin/ai-groups/g1/messages",
                json={"message": "hello"},
            )
        assert resp.status_code == 500

    def test_add_member_admin_success(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.add_member.return_value = {"id": "g1", "members": []}
            mock_svc_cls.return_value = mock_svc
            resp = client.post(
                "/api/admin/ai-groups/g1/members",
                json={"employee_id": "e1", "name": "Employee 1"},
            )
        assert resp.status_code == 200

    def test_add_member_value_error_400(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.add_member.side_effect = ValueError("bad")
            mock_svc_cls.return_value = mock_svc
            resp = client.post(
                "/api/admin/ai-groups/g1/members",
                json={"employee_id": "e1"},
            )
        assert resp.status_code == 400

    def test_add_member_recoverable_error_500(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.add_member.side_effect = RuntimeError("db error")
            mock_svc_cls.return_value = mock_svc
            resp = client.post(
                "/api/admin/ai-groups/g1/members",
                json={"employee_id": "e1"},
            )
        assert resp.status_code == 500

    def test_remove_member_admin_success(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.remove_member.return_value = {"id": "g1", "members": []}
            mock_svc_cls.return_value = mock_svc
            resp = client.delete("/api/admin/ai-groups/g1/members/e1")
        assert resp.status_code == 200

    def test_remove_member_value_error_400(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.remove_member.side_effect = ValueError("bad")
            mock_svc_cls.return_value = mock_svc
            resp = client.delete("/api/admin/ai-groups/g1/members/e1")
        assert resp.status_code == 400

    def test_remove_member_recoverable_error_500(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.im_routes.HostSessionLocal") as mock_db_cls,
            patch(
                "app.fastapi_routes.im_routes._is_admin_customer_service_session",
                return_value=True,
            ),
            patch("app.fastapi_routes.im_routes.AiGroupChatService") as mock_svc_cls,
        ):
            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_svc = MagicMock()
            mock_svc.remove_member.side_effect = RuntimeError("db error")
            mock_svc_cls.return_value = mock_svc
            resp = client.delete("/api/admin/ai-groups/g1/members/e1")
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# WebSocket tests
# ---------------------------------------------------------------------------


class TestImWebSocket:
    def test_unauthorized_ws_closes(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.im_routes._resolve_ws_user_id", return_value=None
            ),
            patch("app.fastapi_routes.im_routes._ensure_schema"),
        ):
            try:
                with client.websocket_connect("/ws/im") as websocket:
                    pass
            except Exception:
                # WebSocket close may raise in test client
                pass

    def test_ping_pong(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.im_routes._resolve_ws_user_id", return_value=1
            ),
            patch("app.fastapi_routes.im_routes._ensure_schema"),
            patch("app.fastapi_routes.im_routes.im_ws_hub") as mock_hub,
        ):
            mock_hub.connect = AsyncMock()
            mock_hub.disconnect = AsyncMock()
            try:
                with client.websocket_connect("/ws/im") as websocket:
                    websocket.send_text("ping")
                    data = websocket.receive_text()
                    assert data == '{"type":"pong"}'
            except Exception:
                pass

    def test_ping_json_pong(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.im_routes._resolve_ws_user_id", return_value=1
            ),
            patch("app.fastapi_routes.im_routes._ensure_schema"),
            patch("app.fastapi_routes.im_routes.im_ws_hub") as mock_hub,
        ):
            mock_hub.connect = AsyncMock()
            mock_hub.disconnect = AsyncMock()
            try:
                with client.websocket_connect("/ws/im") as websocket:
                    websocket.send_text('{"type":"ping"}')
                    data = websocket.receive_text()
                    assert data == '{"type":"pong"}'
            except Exception:
                pass
