"""移动端 API 扩展路由测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.fastapi_routes.mobile_api as _mobile_api_mod  # noqa: F401,E402 — must precede mobile_api_extensions to break circular import
from app.fastapi_routes import mobile_api_extensions as mobile_ext  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("LAN_GUARD_ENABLED", "0")
    monkeypatch.setenv("LAN_CIDR_GUARD_ENABLED", "0")
    from app.fastapi_app.factory import create_fastapi_app

    return TestClient(create_fastapi_app(enable_cors=False))


def test_pairing_issue_and_exchange(monkeypatch):
    # 配对签发仅限桌面模式下的本机回环请求；交换要求已登录的移动用户。
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    monkeypatch.setattr(
        mobile_ext,
        "_register_desktop_relay_for_pairing",
        lambda host, port: {
            "relay_id": "r1",
            "pairing_code": "123456",
            "relay_base_url": "https://relay.example.com",
            "exp": 4102444800,
        },
    )
    app = FastAPI()
    app.include_router(mobile_ext.extension_router, prefix="/api/mobile/v1")
    app.dependency_overrides[mobile_ext.get_mobile_user] = lambda: SimpleNamespace(
        id=7, is_active=True, role="enterprise"
    )
    client = TestClient(app, base_url="http://127.0.0.1:17500", client=("127.0.0.1", 17500))

    issue = client.post(
        "/api/mobile/v1/pairing/issue",
        json={"host": "192.168.1.10", "port": 5000},
    )
    assert issue.status_code == 200, issue.text
    body = issue.json()
    assert body.get("success") is True
    nonce = body.get("data", {}).get("nonce")
    assert nonce
    ex = client.post("/api/mobile/v1/pairing/exchange", json={"nonce": nonce})
    assert ex.status_code == 200, ex.text
    assert ex.json().get("data", {}).get("host") == "192.168.1.10"


def test_mobile_mods_requires_auth(client: TestClient):
    r = client.get("/api/mobile/v1/mods")
    assert r.status_code in (401, 403)
