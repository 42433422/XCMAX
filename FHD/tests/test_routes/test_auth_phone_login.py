"""Legacy SMS endpoints report unavailable without authenticating or sending messages."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.fastapi_routes.domains.auth.auth_routes import router as auth_router
    from app.fastapi_routes.market_account import router as market_router
    from app.fastapi_routes.mobile_api import router as mobile_router

    app = FastAPI()
    for router in (auth_router, market_router, mobile_router):
        app.include_router(router)
    return TestClient(app)


def test_login_with_phone_code_invalid_input(client: TestClient) -> None:
    response = client.post("/api/auth/login-with-phone-code", json={"phone": "", "code": ""})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INPUT"


@pytest.mark.parametrize("provider", ["", "configured-provider"])
@pytest.mark.parametrize(
    "path",
    [
        "/api/auth/login-with-phone-code",
        "/api/market/send-phone-code",
        "/api/market/login-with-phone-code",
        "/api/mobile/v1/auth/login-with-phone-code",
    ],
)
def test_sms_is_unavailable_without_upstream_or_session_side_effects(
    client, monkeypatch, provider, path
):
    monkeypatch.setenv("SMS_PROVIDER", provider)
    with (
        patch("app.fastapi_routes.market_account._proxy_json", new_callable=AsyncMock) as upstream,
        patch(
            "app.application.enterprise_login_flow.run_market_first_login", new_callable=AsyncMock
        ) as login,
    ):
        response = client.post(path, json={"phone": "13800138000", "code": "123456"})
    assert response.status_code == 501, response.text
    payload = response.json()
    assert payload["success"] is False
    detail = payload["data"] if path.startswith("/api/mobile/") else payload
    assert detail["error_code"] == "SMS_AUTH_UNAVAILABLE"
    assert detail["capability"] == {"id": "sms_login", "available": False}
    assert "当前版本不支持" in payload["message"]
    assert "set-cookie" not in response.headers
    upstream.assert_not_awaited()
    login.assert_not_awaited()
    assert client.app.openapi()["paths"][path]["post"]["deprecated"] is True
