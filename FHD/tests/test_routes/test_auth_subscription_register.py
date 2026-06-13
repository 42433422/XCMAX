"""自助注册试用租户与订阅状态 API。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
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


def test_subscription_status_requires_login(client: TestClient) -> None:
    resp = client.get("/api/auth/subscription/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("success") is False


def test_subscription_status_trial(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_user = SimpleNamespace(id=42, role="viewer", username="trial-user", is_active=True)

    with (
        patch(
            "app.fastapi_routes.domains.auth.routes.resolve_session_user",
            return_value=fake_user,
        ),
        patch(
            "app.application.tenant_subscription_app_service.subscription_status_for_user",
            return_value={
                "active": True,
                "reason": "trial",
                "trial_days_remaining": 13,
            },
        ),
    ):
        resp = client.get("/api/auth/subscription/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("success") is True
    assert body["data"]["reason"] == "trial"


def test_register_enriches_tenant_id(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FHD_ALLOW_OPEN_REGISTRATION", "1")

    created_user = {"success": True, "user_id": 7}
    login_result = {
        "success": True,
        "session_id": "sess-reg-1",
        "user": {"id": 7, "username": "newbie"},
    }

    with (
        patch("app.mod_sdk.product_skus.resolve_product_sku", return_value="generic"),
        patch(
            "app.application.get_user_app_service",
        ) as mock_user_svc,
        patch(
            "app.application.auth_app_service.get_auth_app_service",
        ) as mock_auth_svc,
        patch(
            "app.application.enterprise_login_flow.bind_tenant_for_login",
            return_value={"tenant_id": 99, "tenant_name": "newbie"},
        ) as mock_bind,
        patch(
            "app.application.session_account_meta.persist_session_account_meta",
        ) as mock_persist,
        patch(
            "app.fastapi_routes.market_account.login_market_with_password",
            new=AsyncMock(return_value={"success": False}),
        ),
    ):
        mock_user_svc.return_value.create_user.return_value = created_user
        mock_auth_svc.return_value.login.return_value = login_result

        resp = client.post(
            "/api/auth/register",
            json={"username": "newbie", "password": "secret12"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success") is True
    assert body.get("tenant_id") == 99
    mock_bind.assert_called_once()
    mock_persist.assert_called_once()
