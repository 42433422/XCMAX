"""手机验证码登录路由（mock 市场）。"""

from __future__ import annotations

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


def test_login_with_phone_code_invalid_input(client: TestClient) -> None:
    resp = client.post("/api/auth/login-with-phone-code", json={"phone": "", "code": ""})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_INPUT"


def test_login_with_phone_code_market_fail(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")

    async def _fail(phone: str, code: str):
        return {
            "success": False,
            "message": "验证码无效",
            "status_code": 401,
            "market_base_url": "http://test",
        }

    with patch(
        "app.fastapi_routes.market_account.login_market_with_phone_code",
        new=AsyncMock(side_effect=_fail),
    ):
        resp = client.post(
            "/api/auth/login-with-phone-code",
            json={"phone": "13800138000", "code": "123456", "account_kind": "enterprise"},
        )
    assert resp.status_code == 401


def test_market_send_phone_code_proxy(client: TestClient) -> None:
    with patch(
        "app.fastapi_routes.market_account.send_market_phone_code",
        new=AsyncMock(return_value={"success": True, "message": "验证码已发送"}),
    ):
        resp = client.post("/api/market/send-phone-code", json={"phone": "13800138000"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True
