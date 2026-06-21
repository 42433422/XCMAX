"""OIDC → MODstore JWT 桥接单测。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_login_market_for_oidc_profile_uses_internal_bridge(monkeypatch):
    from app.fastapi_routes import market_account as ma

    monkeypatch.setenv("XCAGI_MARKET_INTERNAL_API_KEY", "test-internal-key")
    profile = {"preferred_username": "sso-user", "email": "sso@example.com", "sub": "sub-1"}

    with patch.object(
        ma,
        "_proxy_json",
        new=AsyncMock(
            side_effect=[
                # 1) IdP bearer 探测：GET /api/auth/me（Bearer oidc-bearer）→ 失败，转内部桥接
                {"__proxy_error__": True, "status_code": 401, "payload": {}},
                # 2) 内部桥接签发：POST /api/auth/internal/sso-issue-token → 返回市场 JWT
                {
                    "success": True,
                    "data": {
                        "token": "market-jwt",
                        "refresh_token": "market-rt",
                        "user": {"id": 1, "username": "sso-user", "is_enterprise": True},
                    },
                },
                # 3) _normalize_market_auth_payload 内部用市场 JWT 拉取身份：
                #    GET /api/auth/me（Bearer market-jwt）
                {
                    "success": True,
                    "user": {"id": 1, "username": "sso-user", "is_enterprise": True},
                },
            ]
        ),
    ) as proxy_mock:
        result = await ma.login_market_for_oidc_profile(profile, oidc_access_token="oidc-bearer")

    assert result.get("success") is True
    assert result.get("token") == "market-jwt"
    assert proxy_mock.await_count == 3
    bridge_call = proxy_mock.await_args_list[1]
    assert bridge_call.args[0] == "POST"
    assert bridge_call.args[1] == "/api/auth/internal/sso-issue-token"
    assert bridge_call.kwargs["extra_headers"]["X-Internal-Api-Key"] == "test-internal-key"
    # 第 3 次调用确认是用市场 JWT 拉取身份
    me_call = proxy_mock.await_args_list[2]
    assert me_call.args == ("GET", "/api/auth/me")
    assert me_call.kwargs["authorization"] == "Bearer market-jwt"


@pytest.mark.asyncio
async def test_finalize_auth_after_oidc_delegates_market_sync():
    from app.application import enterprise_login_flow as flow

    auth_result = {"success": True, "session_id": "sid", "user": {"username": "u", "id": 9}}
    market_ok = {
        "success": True,
        "token": "mtok",
        "refresh_token": "mrt",
        "is_enterprise": True,
        "is_market_admin": False,
    }
    with (
        patch(
            "app.fastapi_routes.market_account.login_market_for_oidc_profile",
            new=AsyncMock(return_value=market_ok),
        ) as market_mock,
        patch(
            "app.application.enterprise_login_flow.finalize_enterprise_login",
            new=AsyncMock(return_value={**auth_result, "market_access_token": "mtok"}),
        ) as finalize_mock,
    ):
        out = await flow.finalize_auth_after_oidc(
            auth_result=auth_result,
            oidc_profile={"email": "u@example.com"},
            oidc_access_token="oidc-at",
            account_kind="enterprise",
            sku="enterprise",
        )

    assert out.get("market_access_token") == "mtok"
    market_mock.assert_awaited_once()
    finalize_mock.assert_awaited_once()
    assert finalize_mock.await_args.kwargs["skip_market_sync"] is False
