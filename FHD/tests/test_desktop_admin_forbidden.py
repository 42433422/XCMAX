"""桌面端禁止管理员登录 / 存量会话（管理端仅网页 SSOT）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.application.desktop_admin_gate import (
    DESKTOP_ADMIN_FORBIDDEN_CODE,
    DESKTOP_ADMIN_FORBIDDEN_MESSAGE,
    assert_desktop_allows_session,
    assert_desktop_allows_session_id,
    forbidden_payload,
    is_desktop_admin_api_path,
    reject_admin_on_desktop,
)
from app.application.enterprise_login_flow import _reject_admin_on_desktop


def test_reject_admin_on_desktop_noop_for_enterprise() -> None:
    assert _reject_admin_on_desktop(session_id="s1", account_kind="enterprise") is None


def test_reject_admin_on_desktop_noop_when_not_desktop() -> None:
    with patch(
        "app.application.enterprise_login_flow._is_desktop_runtime",
        return_value=False,
    ):
        assert _reject_admin_on_desktop(session_id="s1", account_kind="admin") is None


def test_reject_admin_on_desktop_deletes_session() -> None:
    sm = MagicMock()
    with (
        patch(
            "app.application.enterprise_login_flow._is_desktop_runtime",
            return_value=True,
        ),
        patch(
            "app.infrastructure.session.get_session_manager",
            return_value=sm,
        ),
    ):
        denied = _reject_admin_on_desktop(session_id="sid-admin", account_kind="admin")
    assert denied is not None
    assert denied["success"] is False
    assert denied["error"]["code"] == DESKTOP_ADMIN_FORBIDDEN_CODE
    assert DESKTOP_ADMIN_FORBIDDEN_MESSAGE in denied["message"]
    sm.delete_session.assert_called_once_with("sid-admin")


def test_assert_desktop_allows_session_deletes_admin() -> None:
    sm = MagicMock()
    with (
        patch("app.application.desktop_admin_gate.is_desktop_runtime", return_value=True),
        patch("app.infrastructure.session.get_session_manager", return_value=sm),
    ):
        denied = assert_desktop_allows_session({"account_kind": "admin"}, session_id="legacy-admin")
    assert denied is not None
    assert denied["error"]["code"] == DESKTOP_ADMIN_FORBIDDEN_CODE
    sm.delete_session.assert_called_once_with("legacy-admin")


def test_assert_desktop_allows_session_id_loads_meta() -> None:
    sm = MagicMock()
    with (
        patch("app.application.desktop_admin_gate.is_desktop_runtime", return_value=True),
        patch(
            "app.application.session_account_meta.load_session_account_meta",
            return_value={"account_kind": "admin"},
        ),
        patch("app.infrastructure.session.get_session_manager", return_value=sm),
    ):
        denied = assert_desktop_allows_session_id("sid-x")
    assert denied is not None
    sm.delete_session.assert_called_once_with("sid-x")


def test_auth_permission_admin_shell_blocked_on_desktop_mode() -> None:
    from app.application.auth_permission_resolver import resolve_permissions

    with patch("app.application.desktop_admin_gate.is_desktop_runtime", return_value=True):
        decision = resolve_permissions(
            user=MagicMock(account_kind="admin", tier="admin", role="admin"),
            account_kind="admin",
            session_meta={},
            route="/api/auth/me",
        )
    assert decision["admin_shell_blocked"] is True
    assert decision["allowed"] is False


def test_desktop_admin_api_path_prefixes() -> None:
    assert is_desktop_admin_api_path("/api/admin/foo")
    assert is_desktop_admin_api_path("/api/xcmax/admin/modules")
    assert is_desktop_admin_api_path("/api/mobile/v1/admin/employees")
    assert not is_desktop_admin_api_path("/api/auth/me")
    assert not is_desktop_admin_api_path("/api/xcmax/sync/status")


def test_forbidden_payload_shape() -> None:
    body = forbidden_payload()
    assert body["error"]["code"] == DESKTOP_ADMIN_FORBIDDEN_CODE
    assert body["valid"] is False


def test_gate_reject_alias() -> None:
    with patch("app.application.desktop_admin_gate.is_desktop_runtime", return_value=False):
        assert reject_admin_on_desktop(session_id="s", account_kind="admin") is None
