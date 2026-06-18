"""测试 auth_decorators 模块的登录、角色、权限装饰器。"""

from unittest.mock import MagicMock, patch

import pytest

from app.auth_decorators import (
    _current_user_ctx,
    _session_id_ctx,
    get_current_session_id,
    get_current_user,
    login_required,
    permission_required,
    role_required,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeUser:
    def __init__(self, role="user", is_active=True):
        self.role = role
        self.is_active = is_active
        self.id = 1
        self.username = "testuser"


def _make_view_func(return_value="ok"):
    """创建一个简单的视图函数用于装饰器测试。"""

    def view_func(*args, **kwargs):
        return return_value

    return view_func


# ---------------------------------------------------------------------------
# get_current_user / get_current_session_id
# ---------------------------------------------------------------------------


class TestContextVars:
    def test_get_current_user_default_none(self):
        _current_user_ctx.set(None)
        assert get_current_user() is None

    def test_get_current_user_with_value(self):
        user = _FakeUser()
        _current_user_ctx.set(user)
        assert get_current_user() is user
        _current_user_ctx.set(None)

    def test_get_current_session_id_default_none(self):
        _session_id_ctx.set(None)
        assert get_current_session_id() is None

    def test_get_current_session_id_with_value(self):
        _session_id_ctx.set("abc123")
        assert get_current_session_id() == "abc123"
        _session_id_ctx.set(None)


# ---------------------------------------------------------------------------
# _extract_session_id
# ---------------------------------------------------------------------------


class TestExtractSessionId:
    @patch("app.http.request_context.get_current_http_request", return_value=None)
    def test_no_request_returns_none(self, _mock_req):
        from app.auth_decorators import _extract_session_id

        assert _extract_session_id() is None

    @patch("app.http.request_context.get_current_http_request")
    def test_bearer_token(self, mock_get_req):
        from app.auth_decorators import _extract_session_id

        req = MagicMock()
        req.headers = {"Authorization": "Bearer mytoken123"}
        req.cookies = {}
        mock_get_req.return_value = req
        assert _extract_session_id() == "mytoken123"

    @patch("app.http.request_context.get_current_http_request")
    def test_cookie_session(self, mock_get_req):
        from app.auth_decorators import _extract_session_id

        req = MagicMock()
        req.headers = {}
        req.cookies = {"session_id": "cookie_sid"}
        mock_get_req.return_value = req
        assert _extract_session_id() == "cookie_sid"

    @patch("app.http.request_context.get_current_http_request")
    def test_no_auth_header_no_cookie(self, mock_get_req):
        from app.auth_decorators import _extract_session_id

        req = MagicMock()
        req.headers = {}
        req.cookies = {}
        mock_get_req.return_value = req
        assert _extract_session_id() is None

    @patch("app.http.request_context.get_current_http_request")
    def test_non_bearer_auth_header(self, mock_get_req):
        from app.auth_decorators import _extract_session_id

        req = MagicMock()
        req.headers = {"Authorization": "Basic abc"}
        req.cookies = {}
        mock_get_req.return_value = req
        # Should fall through to cookie, which is empty
        assert _extract_session_id() is None


# ---------------------------------------------------------------------------
# login_required
# ---------------------------------------------------------------------------


class TestLoginRequired:
    @patch("app.auth_decorators._extract_session_id", return_value=None)
    def test_no_session_id_returns_401(self, _mock):
        decorated = login_required(_make_view_func())
        result = decorated()
        assert isinstance(result, tuple)
        assert result[1] == 401

    @patch("app.auth_decorators._extract_session_id", return_value="sid123")
    @patch("app.auth_decorators.get_session_service")
    def test_invalid_session_returns_401(self, mock_get_ss, _mock):
        ss = MagicMock()
        ss.validate_session.return_value = None
        mock_get_ss.return_value = ss
        decorated = login_required(_make_view_func())
        result = decorated()
        assert isinstance(result, tuple)
        assert result[1] == 401

    @patch("app.auth_decorators._extract_session_id", return_value="sid123")
    @patch("app.auth_decorators.get_session_service")
    def test_inactive_user_returns_403(self, mock_get_ss, _mock):
        ss = MagicMock()
        ss.validate_session.return_value = _FakeUser(is_active=False)
        mock_get_ss.return_value = ss
        decorated = login_required(_make_view_func())
        result = decorated()
        assert isinstance(result, tuple)
        assert result[1] == 403

    @patch("app.auth_decorators._extract_session_id", return_value="sid123")
    @patch("app.auth_decorators.get_session_service")
    def test_active_user_calls_view(self, mock_get_ss, _mock):
        ss = MagicMock()
        ss.validate_session.return_value = _FakeUser(is_active=True)
        mock_get_ss.return_value = ss
        decorated = login_required(_make_view_func("success"))
        result = decorated()
        assert result == "success"

    @patch("app.auth_decorators._extract_session_id", return_value="sid123")
    @patch("app.auth_decorators.get_session_service")
    def test_context_vars_set_and_reset(self, mock_get_ss, _mock):
        ss = MagicMock()
        user = _FakeUser(is_active=True)
        ss.validate_session.return_value = user
        mock_get_ss.return_value = ss

        _current_user_ctx.set(None)
        _session_id_ctx.set(None)

        def check_context():
            # Inside the decorated function, context should be set
            assert get_current_user() is user
            assert get_current_session_id() == "sid123"
            return "checked"

        decorated = login_required(check_context)
        decorated()

        # After the decorated function, context should be reset
        assert get_current_user() is None
        assert get_current_session_id() is None

    @patch("app.auth_decorators._extract_session_id", return_value="sid123")
    @patch("app.auth_decorators.get_session_service")
    def test_context_reset_on_exception(self, mock_get_ss, _mock):
        ss = MagicMock()
        ss.validate_session.return_value = _FakeUser(is_active=True)
        mock_get_ss.return_value = ss

        _current_user_ctx.set(None)
        _session_id_ctx.set(None)

        def raise_error():
            raise ValueError("boom")

        decorated = login_required(raise_error)
        with pytest.raises(ValueError, match="boom"):
            decorated()

        # Context should still be reset even after exception
        assert get_current_user() is None
        assert get_current_session_id() is None


# ---------------------------------------------------------------------------
# role_required
# ---------------------------------------------------------------------------


class TestRoleRequired:
    def test_no_user_returns_401(self):
        _current_user_ctx.set(None)
        decorated = role_required(["admin"])(_make_view_func())
        result = decorated()
        assert isinstance(result, tuple)
        assert result[1] == 401

    def test_user_without_role_returns_403(self):
        user = _FakeUser(role="user")
        _current_user_ctx.set(user)
        decorated = role_required(["admin"])(_make_view_func())
        result = decorated()
        assert isinstance(result, tuple)
        assert result[1] == 403
        _current_user_ctx.set(None)

    def test_user_with_matching_role_passes(self):
        user = _FakeUser(role="manager")
        _current_user_ctx.set(user)
        decorated = role_required(["manager"])(_make_view_func("ok"))
        result = decorated()
        assert result == "ok"
        _current_user_ctx.set(None)

    def test_admin_always_passes(self):
        user = _FakeUser(role="admin")
        _current_user_ctx.set(user)
        decorated = role_required(["manager", "super"])(_make_view_func("admin_ok"))
        result = decorated()
        assert result == "admin_ok"
        _current_user_ctx.set(None)

    def test_multiple_roles_one_match(self):
        user = _FakeUser(role="editor")
        _current_user_ctx.set(user)
        decorated = role_required(["admin", "editor"])(_make_view_func("editor_ok"))
        result = decorated()
        assert result == "editor_ok"
        _current_user_ctx.set(None)


# ---------------------------------------------------------------------------
# permission_required
# ---------------------------------------------------------------------------


class TestPermissionRequired:
    def test_no_user_returns_401(self):
        _current_user_ctx.set(None)
        decorated = permission_required("product:create")(_make_view_func())
        result = decorated()
        assert isinstance(result, tuple)
        assert result[1] == 401

    @patch("app.auth_decorators.get_auth_service")
    def test_user_without_permission_returns_403(self, mock_get_auth):
        auth = MagicMock()
        auth.has_permission.return_value = False
        mock_get_auth.return_value = auth
        user = _FakeUser()
        _current_user_ctx.set(user)
        decorated = permission_required("product:delete")(_make_view_func())
        result = decorated()
        assert isinstance(result, tuple)
        assert result[1] == 403
        _current_user_ctx.set(None)

    @patch("app.auth_decorators.get_auth_service")
    def test_user_with_permission_passes(self, mock_get_auth):
        auth = MagicMock()
        auth.has_permission.return_value = True
        mock_get_auth.return_value = auth
        user = _FakeUser()
        _current_user_ctx.set(user)
        decorated = permission_required("product:read")(_make_view_func("granted"))
        result = decorated()
        assert result == "granted"
        _current_user_ctx.set(None)

    @patch("app.auth_decorators.get_auth_service")
    def test_has_permission_called_with_correct_code(self, mock_get_auth):
        auth = MagicMock()
        auth.has_permission.return_value = True
        mock_get_auth.return_value = auth
        user = _FakeUser()
        _current_user_ctx.set(user)
        decorated = permission_required("order:export")(_make_view_func())
        decorated()
        auth.has_permission.assert_called_once_with(user, "order:export")
        _current_user_ctx.set(None)
