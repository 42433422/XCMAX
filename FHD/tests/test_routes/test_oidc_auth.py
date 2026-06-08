"""OIDC 路由：状态、回调重定向与会话 Cookie。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from app.infrastructure.auth.oidc_provider import sign_oidc_state
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _disable_lan_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAN_GUARD_ENABLED", "0")
    from app.security.lan_config import reset_lan_config_cache
    from app.security.lan_settings_store import LanSettingsOverride

    monkeypatch.setattr(
        "app.security.lan_settings_store.load_overrides",
        lambda: LanSettingsOverride(enabled=False),
    )
    reset_lan_config_cache()


def test_oidc_status_disabled(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_OIDC_ENABLED", raising=False)
    resp = client.get("/api/auth/oidc/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("success") is True
    assert body.get("data", {}).get("enabled") is False


def test_oidc_status_enabled(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_OIDC_ENABLED", "1")
    resp = client.get("/api/auth/oidc/status")
    assert resp.status_code == 200
    assert resp.json()["data"]["enabled"] is True


def test_oidc_callback_invalid_state_redirects(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XCAGI_OIDC_ENABLED", "1")
    monkeypatch.setenv("XCAGI_OIDC_FRONTEND_REDIRECT", "/login")
    resp = client.get("/api/auth/oidc/callback?code=abc&state=bad", follow_redirects=False)
    assert resp.status_code == 302
    assert "oidc_error=OIDC_STATE" in resp.headers.get("location", "")


def test_oidc_callback_success_redirects_with_session(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XCAGI_OIDC_ENABLED", "1")
    monkeypatch.setenv("XCAGI_OIDC_FRONTEND_REDIRECT", "/login")
    monkeypatch.setenv("XCAGI_OIDC_ISSUER", "https://idp.example/realms/test")
    monkeypatch.setenv("XCAGI_OIDC_CLIENT_ID", "fhd-web")
    monkeypatch.setenv("XCAGI_OIDC_REDIRECT_URI", "http://testserver/api/auth/oidc/callback")
    state = sign_oidc_state()

    profile = {"preferred_username": "oidc-user", "email": "oidc@example.com", "name": "OIDC User"}
    auth_result = {
        "success": True,
        "session_id": "sess-oidc-1",
        "user": {"id": 9, "username": "oidc-user"},
    }

    with (
        patch(
            "app.infrastructure.auth.oidc_provider.exchange_code_for_userinfo",
            new_callable=AsyncMock,
            return_value=profile,
        ),
        patch(
            "app.application.auth_app_service.get_auth_app_service",
        ) as mock_get_auth,
    ):
        mock_get_auth.return_value.authenticate_oidc_user.return_value = auth_result
        resp = client.get(
            f"/api/auth/oidc/callback?code=good-code&state={state}",
            follow_redirects=False,
        )

    assert resp.status_code == 302
    location = resp.headers.get("location", "")
    assert "oidc=ok" in location
    cookie_name = "session_id"
    assert cookie_name in resp.cookies or any(
        cookie_name in k for k in resp.headers.get("set-cookie", "")
    )
