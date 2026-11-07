"""Configuring SMS_PROVIDER must not advertise an unimplemented SMS capability."""

from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.mark.parametrize("provider", [None, "", "configured-provider"])
@pytest.mark.parametrize("path", ["/auth/send-phone-code", "/auth/login-with-phone-code"])
def test_sms_compatibility_error_is_provider_independent(monkeypatch, provider, path):
    from modstore_server import market_auth_api

    if provider is None:
        monkeypatch.delenv("SMS_PROVIDER", raising=False)
    else:
        monkeypatch.setenv("SMS_PROVIDER", provider)
    session = Mock(side_effect=AssertionError("SMS must not create a user or verification code"))
    monkeypatch.setattr(market_auth_api, "get_session_factory", session)
    app = FastAPI()
    app.include_router(market_auth_api.router, prefix="/api")
    with TestClient(app) as client:
        response = client.post(f"/api{path}", json={"phone": "13800138000", "code": "123456"})
    assert response.status_code == 501
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "SMS_AUTH_UNAVAILABLE"
    assert payload["error_code"] == "SMS_AUTH_UNAVAILABLE"
    assert payload["capability"] == {"id": "sms_login", "available": False}
    assert "当前版本不支持" in payload["message"]
    assert "set-cookie" not in response.headers
    session.assert_not_called()
    assert app.openapi()["paths"][f"/api{path}"]["post"]["deprecated"] is True
