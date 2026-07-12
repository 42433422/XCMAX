"""桌面端禁止管理员登录（管理端仅网页 SSOT）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.application.enterprise_login_flow import (
    DESKTOP_ADMIN_FORBIDDEN_CODE,
    DESKTOP_ADMIN_FORBIDDEN_MESSAGE,
    _reject_admin_on_desktop,
)


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
