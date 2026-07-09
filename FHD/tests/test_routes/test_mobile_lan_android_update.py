"""LAN 手机自更新：android-update 元数据 API。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True, scope="module")
def _resolve_circular_import():
    if "app.fastapi_routes.mobile_api_extensions" not in sys.modules:
        from app.fastapi_routes import mobile_api  # noqa: F401
    yield


@pytest.fixture()
def m():
    return sys.modules["app.fastapi_routes.mobile_api_extensions"]


@pytest.fixture()
def dnr():
    import app.fastapi_routes.mobile_extensions.device_notify_routes as mod

    return mod


@pytest.fixture()
def lan_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, m, dnr) -> TestClient:
    root = tmp_path / "lan-releases"
    sku_dir = root / "enterprise"
    sku_dir.mkdir(parents=True)
    apk = sku_dir / "XCAGI-Enterprise-Android-10.0.0.apk"
    apk.write_bytes(b"apk-bytes")
    (sku_dir / "manifest.json").write_text(
        json.dumps(
            {
                "sku": "enterprise",
                "version_code": 1783600000,
                "version_name": "10.0.0",
                "apk_path": "enterprise/XCAGI-Enterprise-Android-10.0.0.apk",
                "apk_name": "XCAGI-Enterprise-Android-10.0.0.apk",
                "sha256": "abc",
                "built_at": "2026-07-09T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    # 路由闭包引用的是 device_notify_routes 模块内符号
    monkeypatch.setattr(dnr, "_lan_releases_root", lambda: root)
    monkeypatch.setattr(m, "_lan_releases_root", lambda: root)

    app = FastAPI()
    app.include_router(m.extension_router, prefix="/api/mobile/v1")

    async def _user():
        return MagicMock(user_id=1)

    app.dependency_overrides[m.get_mobile_user] = _user
    return TestClient(app)


def test_lan_android_update_returns_download_url(lan_app: TestClient) -> None:
    resp = lan_app.get(
        "/api/mobile/v1/lan/android-update",
        params={"sku": "enterprise", "current_version_code": 10},
        headers={"Host": "192.168.10.2:17500"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["latest_android_version"] == 1783600000
    assert data["latest_android_version_name"] == "10.0.0"
    assert data["available"] is True
    assert data["apk_download_url"].endswith(
        "/download/lan/enterprise/XCAGI-Enterprise-Android-10.0.0.apk"
    )
    assert "192.168.10.2:17500" in data["apk_download_url"]


def test_lan_android_update_missing_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, m, dnr
) -> None:
    monkeypatch.setattr(dnr, "_lan_releases_root", lambda: tmp_path / "empty")
    monkeypatch.setattr(m, "_lan_releases_root", lambda: tmp_path / "empty")
    app = FastAPI()
    app.include_router(m.extension_router, prefix="/api/mobile/v1")

    async def _user():
        return MagicMock(user_id=1)

    app.dependency_overrides[m.get_mobile_user] = _user
    client = TestClient(app)
    resp = client.get("/api/mobile/v1/lan/android-update")
    assert resp.status_code == 404


def test_lan_android_update_notify_loopback(
    lan_app: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple] = []

    def _fake_notify(user_id, title, body, data=None):
        calls.append((user_id, title, body, data))
        return {"fcm": False, "outbox": True}

    monkeypatch.setattr(
        "app.application.mobile_push_app_service.notify_mobile_user",
        _fake_notify,
    )
    resp = lan_app.post(
        "/api/mobile/v1/lan/android-update/notify",
        json={"sku": "enterprise", "version_code": 1783600000, "user_ids": [1]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["route"] == "update/check"
    assert calls and calls[0][0] == 1
    assert calls[0][3]["type"] == "lan_apk_ready"


def test_lan_android_update_notify_rejects_non_loopback(
    lan_app: TestClient, monkeypatch: pytest.MonkeyPatch, dnr
) -> None:
    monkeypatch.setattr(dnr, "_is_loopback_request", lambda _request: False)
    resp = lan_app.post(
        "/api/mobile/v1/lan/android-update/notify",
        json={"sku": "enterprise", "user_ids": [1]},
    )
    assert resp.status_code == 403
