"""企业 SKU 市场不可达时的本地离线登录兜底（run_market_first_login 分支）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.enterprise_login_flow import (
    OFFLINE_LOGIN_MESSAGE,
    _market_result_unreachable,
    run_market_first_login,
)


class TestMarketResultUnreachable:
    def test_unavailable_error_code(self):
        assert _market_result_unreachable({"error_code": "MARKET_AUTH_UNAVAILABLE"}) is True

    def test_5xx_status(self):
        assert _market_result_unreachable({"status_code": 502}) is True
        assert _market_result_unreachable({"status_code": 500}) is True

    def test_credential_rejection_is_not_unreachable(self):
        assert _market_result_unreachable({"status_code": 401}) is False
        assert _market_result_unreachable({"status_code": 403, "error_code": "MARKET_AUTH_FAILED"}) is False

    def test_success_is_not_unreachable(self):
        assert _market_result_unreachable({"success": True}) is False

    def test_none_and_invalid(self):
        assert _market_result_unreachable(None) is False
        assert _market_result_unreachable({"status_code": "bad"}) is False


def _unreachable_market_result() -> dict:
    return {
        "success": False,
        "status_code": 502,
        "error_code": "MARKET_AUTH_UNAVAILABLE",
        "message": "无法连接修茈市场",
        "market_base_url": "https://xiu-ci.com",
    }


@pytest.mark.asyncio
async def test_offline_fallback_logs_in_local_enterprise_user():
    auth_service = MagicMock()
    auth_service.login.return_value = {
        "success": True,
        "session_id": "sid-1",
        "user": {"id": 7, "username": "worker", "role": "user"},
    }
    with patch(
        "app.application.enterprise_login_flow.finalize_enterprise_login",
        new=AsyncMock(side_effect=lambda **kw: kw["result"]),
    ), patch(
        "app.application.enterprise_login_flow.persist_session_account_meta"
    ) as persist_mock:
        result, err = await run_market_first_login(
            username="worker",
            password="pw",
            account_kind="enterprise",
            market_result=_unreachable_market_result(),
            auth_app_service=auth_service,
            sku="enterprise",
            jit_create_fn=None,
            market_user_email_from_raw=None,
            login_market_fn=None,
        )
    assert err is None
    assert result is not None
    assert result["offline_login"] is True
    assert result["market_is_enterprise"] is True
    assert result["market_account"]["success"] is False
    assert result["market_account"]["message"] == OFFLINE_LOGIN_MESSAGE
    persist_mock.assert_called_once()


@pytest.mark.asyncio
async def test_offline_fallback_skipped_when_local_password_wrong():
    auth_service = MagicMock()
    auth_service.login.return_value = {"success": False, "message": "用户名或密码错误"}
    result, err = await run_market_first_login(
        username="worker",
        password="wrong",
        account_kind="enterprise",
        market_result=_unreachable_market_result(),
        auth_app_service=auth_service,
        sku="enterprise",
        jit_create_fn=None,
        market_user_email_from_raw=None,
        login_market_fn=None,
    )
    # 本地凭据无效 → 回落到原市场错误响应
    assert result is None
    assert err is not None
    assert b"MARKET_AUTH_UNAVAILABLE" in err.body


@pytest.mark.asyncio
async def test_offline_fallback_rejects_local_admin_at_enterprise_entrance():
    auth_service = MagicMock()
    auth_service.login.return_value = {
        "success": True,
        "session_id": "sid-admin",
        "user": {"id": 1, "username": "admin", "role": "admin"},
    }
    result, err = await run_market_first_login(
        username="admin",
        password="pw",
        account_kind="enterprise",
        market_result=_unreachable_market_result(),
        auth_app_service=auth_service,
        sku="enterprise",
        jit_create_fn=None,
        market_user_email_from_raw=None,
        login_market_fn=None,
    )
    assert result is None
    assert err is not None
    assert b"ACCOUNT_KIND_MISMATCH" in err.body


@pytest.mark.asyncio
async def test_credential_rejection_does_not_trigger_offline_fallback():
    auth_service = MagicMock()
    auth_service.login.return_value = {
        "success": True,
        "session_id": "sid-1",
        "user": {"id": 7, "username": "worker", "role": "user"},
    }
    rejected = {
        "success": False,
        "status_code": 401,
        "error_code": "MARKET_AUTH_FAILED",
        "message": "用户名或密码错误",
    }
    result, err = await run_market_first_login(
        username="worker",
        password="pw",
        account_kind="enterprise",
        market_result=rejected,
        auth_app_service=auth_service,
        sku="enterprise",
        jit_create_fn=None,
        market_user_email_from_raw=None,
        login_market_fn=None,
    )
    # 市场明确拒绝凭据（4xx）时不得离线放行
    assert result is None
    assert err is not None
    auth_service.login.assert_not_called()
