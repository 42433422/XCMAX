"""健康检查轻量模式。"""

from __future__ import annotations

import pytest
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
    assert "x-xcagi-desktop-proof" not in ping.headers


def test_desktop_ping_proves_the_child_environment_without_returning_it(monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    monkeypatch.setenv("XCAGI_DESKTOP_WORKSPACE_TOKEN", "a" * 64)
    app = FastAPI()
    register_health_routes(app)
    with TestClient(app) as client:
        response = client.get("/api/ping", params={"desktop_challenge": "b" * 64})
        changed = client.get("/api/ping", params={"desktop_challenge": "c" * 64})
        normal = client.get("/api/ping")
    assert response.json() == changed.json() == normal.json() == {"pong": True}
    # Independent Node crypto vector: createHmac('sha256', 'a'.repeat(64)).
    # update('xcagi-desktop-backend-v1:' + 'b'.repeat(64)).digest('hex').
    assert response.headers["x-xcagi-desktop-proof"] == (
        "8e62b6c29b476c1131b6b10c8021f6ecaedcb66c6d8d4910fed5cc85720d9803"
    )
    assert changed.headers["x-xcagi-desktop-proof"] != response.headers["x-xcagi-desktop-proof"]
    assert response.headers["cache-control"] == "no-store"
    assert "x-xcagi-desktop-proof" not in normal.headers
    assert "a" * 64 not in response.text + str(dict(response.headers))


@pytest.mark.parametrize(
    ("desktop", "token", "challenge"),
    [
        ("0", "a" * 64, "b" * 64),
        ("1", None, "b" * 64),
        ("1", "", "b" * 64),
        ("1", "a" * 63, "b" * 64),
        ("1", "g" * 64, "b" * 64),
        ("1", "\u00e9" * 64, "b" * 64),
        ("1", "a" * 64, ""),
        ("1", "a" * 64, "b" * 63),
        ("1", "a" * 64, "g" * 64),
        ("1", "a" * 64, "\u00e9" * 64),
    ],
)
def test_ping_never_proves_invalid_or_non_desktop_launches(
    monkeypatch, desktop, token, challenge
) -> None:
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", desktop)
    if token is None:
        monkeypatch.delenv("XCAGI_DESKTOP_WORKSPACE_TOKEN", raising=False)
    else:
        monkeypatch.setenv("XCAGI_DESKTOP_WORKSPACE_TOKEN", token)
    app = FastAPI()
    register_health_routes(app)
    with TestClient(app) as client:
        response = client.get("/api/ping", params={"desktop_challenge": challenge})
    assert response.status_code == 200
    assert response.json() == {"pong": True}
    assert "x-xcagi-desktop-proof" not in response.headers
