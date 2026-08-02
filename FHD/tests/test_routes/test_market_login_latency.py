"""Regression coverage for the official-market password-login critical path."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.fastapi_routes import market_account as market


@pytest.mark.asyncio
async def test_enterprise_claim_from_login_skips_redundant_profile_round_trip(monkeypatch):
    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.example.test")
    login_payload = {
        "access_token": "market-token",
        "refresh_token": "market-refresh",
        "user": {
            "id": 7,
            "username": "enterprise-user",
            "is_enterprise": True,
            "is_admin": False,
        },
    }

    with (
        patch(
            "app.application.surface_audit_demo_account.try_local_demo_market_login",
            return_value=None,
        ),
        patch.object(market, "_proxy_json", new=AsyncMock(return_value=login_payload)) as proxy,
    ):
        result = await market.login_market_with_password("enterprise-user", "password")

    assert result["success"] is True
    assert result["is_enterprise"] is True
    assert proxy.await_count == 1
    assert proxy.await_args.args == ("POST", "/api/auth/login")
    assert proxy.await_args.kwargs["preflight_csrf"] is False
    assert proxy.await_args.kwargs["timeout_seconds"] == 8.0


@pytest.mark.asyncio
async def test_missing_login_claim_keeps_strict_profile_lookup(monkeypatch):
    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.example.test")
    login_payload = {"access_token": "market-token", "user": {"id": 7, "username": "user"}}
    profile_payload = {"user": {"id": 7, "username": "user", "is_enterprise": True}}

    with (
        patch(
            "app.application.surface_audit_demo_account.try_local_demo_market_login",
            return_value=None,
        ),
        patch.object(
            market,
            "_proxy_json",
            new=AsyncMock(side_effect=[login_payload, profile_payload]),
        ) as proxy,
    ):
        result = await market.login_market_with_password("user", "password")

    assert result["success"] is True
    assert result["is_enterprise"] is True
    assert proxy.await_count == 2
    assert proxy.await_args_list[1].args == ("GET", "/api/auth/me")
    assert proxy.await_args_list[1].kwargs["timeout_seconds"] == 8.0


@pytest.mark.asyncio
async def test_login_recovers_once_for_legacy_csrf_enforcement(monkeypatch):
    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.example.test")
    login_payload = {
        "access_token": "market-token",
        "user": {"id": 7, "username": "enterprise-user", "is_enterprise": True},
    }

    with (
        patch(
            "app.application.surface_audit_demo_account.try_local_demo_market_login",
            return_value=None,
        ),
        patch.object(
            market,
            "_proxy_json",
            new=AsyncMock(side_effect=[market.JSONResponse({}, status_code=403), login_payload]),
        ) as proxy,
    ):
        result = await market.login_market_with_password("enterprise-user", "password")

    assert result["success"] is True
    assert proxy.await_count == 2
    assert proxy.await_args_list[0].kwargs["preflight_csrf"] is False
    assert proxy.await_args_list[1].kwargs["preflight_csrf"] is True


def test_market_auth_timeout_is_bounded_and_configurable(monkeypatch):
    monkeypatch.delenv("XCAGI_MARKET_AUTH_TIMEOUT", raising=False)
    assert market._market_auth_timeout() == 8.0

    monkeypatch.setenv("XCAGI_MARKET_AUTH_TIMEOUT", "1")
    assert market._market_auth_timeout() == 3.0

    monkeypatch.setenv("XCAGI_MARKET_AUTH_TIMEOUT", "invalid")
    assert market._market_auth_timeout() == 8.0
