"""桌面设备心跳/在线状态接口单测。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.mobile_extensions.routes_desktop_devices import (
    DesktopDeviceRoutes,
    DesktopDeviceRoutesPorts,
)


class _FakeUser:
    id = 39
    tenant_id = "tenant-a"


def _client(ports: DesktopDeviceRoutesPorts) -> TestClient:
    app = FastAPI()
    routes = DesktopDeviceRoutes(ports, lambda: _FakeUser())
    app.include_router(routes.router, prefix="/api/mobile/v1")
    return TestClient(app)


def test_heartbeat_records_device_for_current_account() -> None:
    captured: dict[str, Any] = {}

    def _heartbeat(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "device_id": kwargs["device_id"],
            "label": kwargs["label"],
            "platform": kwargs["platform"],
            "app_version": kwargs["app_version"],
            "last_seen_at": datetime(2026, 11, 13, 10, 0, 0),
            "online": True,
            "capabilities": kwargs["capabilities"],
        }

    client = _client(
        DesktopDeviceRoutesPorts(
            upsert_heartbeat=_heartbeat,
            list_devices=lambda **_: [],
        )
    )
    response = client.post(
        "/api/mobile/v1/devices/desktop/heartbeat",
        json={
            "device_id": "mac-1",
            "label": "办公室 Mac",
            "platform": "macos",
            "app_version": "1.0.0.7",
            "capabilities": {"folders": ["/Users/a/work"]},
        },
    )
    body = response.json()

    assert response.status_code == 200
    assert body["data"]["device_id"] == "mac-1"
    assert body["data"]["online"] is True
    assert captured["user_id"] == 39
    assert captured["tenant_id"] == "tenant-a"
    assert captured["capabilities"] == {"folders": ["/Users/a/work"]}


def test_heartbeat_requires_device_id() -> None:
    client = _client(
        DesktopDeviceRoutesPorts(
            upsert_heartbeat=lambda **_: {},
            list_devices=lambda **_: [],
        )
    )
    response = client.post("/api/mobile/v1/devices/desktop/heartbeat", json={})
    assert response.status_code == 400
    assert "设备标识" in response.json()["message"]


def test_device_list_marks_offline_devices() -> None:
    now = datetime(2026, 11, 13, 10, 0, 0)
    client = _client(
        DesktopDeviceRoutesPorts(
            upsert_heartbeat=lambda **_: {},
            list_devices=lambda **_: [
                {
                    "device_id": "mac-1",
                    "label": "办公室 Mac",
                    "platform": "macos",
                    "app_version": "1.0.0.7",
                    "last_seen_at": now,
                    "online": True,
                    "capabilities": {},
                },
                {
                    "device_id": "win-1",
                    "label": "家里 Windows",
                    "platform": "windows",
                    "app_version": "1.0.0.6",
                    "last_seen_at": now - timedelta(hours=3),
                    "online": False,
                    "capabilities": {},
                },
            ],
        )
    )
    body = client.get("/api/mobile/v1/devices/desktop").json()

    assert body["data"]["count"] == 2
    assert body["data"]["online_count"] == 1
    assert body["data"]["items"][1]["online"] is False
