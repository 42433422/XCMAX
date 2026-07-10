"""移动端 API 扩展路由测试。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("LAN_GUARD_ENABLED", "0")
    monkeypatch.setenv("LAN_CIDR_GUARD_ENABLED", "0")
    from app.fastapi_routes.mobile_api import get_mobile_user
    from app.fastapi_routes.mobile_api_extensions import extension_router

    app = FastAPI()
    app.include_router(extension_router, prefix="/api/mobile/v1")
    return TestClient(app)


def _admin_user():
    return type(
        "PairingAdmin",
        (),
        {
            "id": 1,
            "username": "admin",
            "display_name": "管理端",
            "role": "admin",
            "tier": "admin",
            "tenant_id": 1,
            "is_active": True,
        },
    )()


def test_pairing_issue_and_exchange(client: TestClient, monkeypatch):
    from app.fastapi_routes import mobile_api_extensions as mobile_ext
    from app.fastapi_routes.mobile_api import get_mobile_user

    client.app.dependency_overrides[get_mobile_user] = lambda: _admin_user()

    monkeypatch.setattr(
        mobile_ext,
        "_pairing_subject_user",
        lambda record: {
            "id": record["subject_user_id"],
            "username": record["subject_username"],
            "role": "enterprise",
            "tenant_id": record["tenant_id"],
            "is_active": True,
        },
    )
    issue = client.post(
        "/api/mobile/v1/pairing/issue",
        json={"host": "192.168.1.10", "port": 5000},
    )
    assert issue.status_code == 200
    body = issue.json()
    assert body.get("success") is True
    nonce = body.get("data", {}).get("nonce")
    assert nonce
    # Exchange is a first-pairing call and therefore intentionally anonymous.
    client.app.dependency_overrides[get_mobile_user] = lambda: None
    ex = client.post("/api/mobile/v1/pairing/exchange", json={"nonce": nonce})
    assert ex.status_code == 200
    assert ex.json().get("data", {}).get("host") == "192.168.1.10"


def test_mobile_mods_requires_auth(client: TestClient):
    r = client.get("/api/mobile/v1/mods")
    assert r.status_code in (401, 403)
