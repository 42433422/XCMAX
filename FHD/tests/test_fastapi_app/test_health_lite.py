"""健康检查轻量模式。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.mounts.health import register_health_routes


def test_health_lite_omits_neuro_payload() -> None:
    app = FastAPI(version="10.0.0")
    register_health_routes(app)
    client = TestClient(app)

    lite = client.get("/api/health", params={"lite": True})
    assert lite.status_code == 200
    body = lite.json()
    assert body["status"] == "healthy"
    assert body["version"] == "10.0.0"
    assert "neuro" not in body

    ping = client.get("/api/ping")
    assert ping.status_code == 200
    assert ping.json() == {"pong": True}
