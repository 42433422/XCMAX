"""RateLimiterMiddleware 挂载与豁免路径行为。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _shared_setup_rate_limiter_high_rate_0(monkeypatch, case_value_1, case_value_2):
    monkeypatch.setenv("MODSTORE_RATE_LIMIT", case_value_1)
    monkeypatch.setenv("MODSTORE_RATE_LIMIT_HIGH", case_value_2)
    monkeypatch.setenv("MODSTORE_RATE_WINDOW", "60")
    monkeypatch.delenv("MODSTORE_REDIS_URL", raising=False)

    from modstore_server.api.rate_limiter import RateLimiterMiddleware

    app = FastAPI()
    return RateLimiterMiddleware, app


pytest.importorskip("starlette")


def test_rate_limiter_exempt_paths_skip_limit(monkeypatch):
    """豁免路径（如 ``/metrics``）在极低 limit 下仍可重复命中。"""
    monkeypatch.setenv("MODSTORE_RATE_LIMIT", "1")
    monkeypatch.setenv("MODSTORE_RATE_WINDOW", "60")
    monkeypatch.delenv("MODSTORE_REDIS_URL", raising=False)

    from modstore_server.api.rate_limiter import RateLimiterMiddleware

    app = FastAPI()

    @app.get("/metrics")
    def metrics():
        return "ok"

    app.add_middleware(RateLimiterMiddleware)
    c = TestClient(app)
    for _ in range(10):
        assert c.get("/metrics").status_code == 200


def test_rate_limiter_returns_429_when_exceeded(monkeypatch):
    monkeypatch.setenv("MODSTORE_RATE_LIMIT", "2")
    monkeypatch.setenv("MODSTORE_RATE_WINDOW", "60")
    monkeypatch.delenv("MODSTORE_REDIS_URL", raising=False)

    from modstore_server.api.rate_limiter import RateLimiterMiddleware

    app = FastAPI()

    @app.get("/hit")
    def hit():
        return {"n": 1}

    app.add_middleware(RateLimiterMiddleware)
    c = TestClient(app)
    assert c.get("/hit").status_code == 200
    assert c.get("/hit").status_code == 200
    r = c.get("/hit")
    assert r.status_code == 429
    assert r.json().get("detail") == "Too many requests"
    assert "Retry-After" in r.headers


def test_rate_limiter_high_rate_get_polling_override(monkeypatch):
    """工作台轮询端点（GET /api/workbench/sessions/{sid}）必须使用更高上限，
    避免 ~450ms 周期的合法轮询触发 429。"""
    RateLimiterMiddleware, app = _shared_setup_rate_limiter_high_rate_0(
        monkeypatch, case_value_1="2", case_value_2="20"
    )

    @app.get("/api/workbench/sessions/{sid}")
    def poll(sid: str):
        return {"id": sid}

    app.add_middleware(RateLimiterMiddleware)
    c = TestClient(app)
    for _ in range(15):
        assert c.get("/api/workbench/sessions/abc").status_code == 200


def test_rate_limiter_high_rate_override_does_not_apply_to_post(monkeypatch):
    """启动会话（POST /api/workbench/sessions）属于昂贵写入，仍走全局限额。"""
    RateLimiterMiddleware, app = _shared_setup_rate_limiter_high_rate_0(
        monkeypatch, case_value_1="2", case_value_2="200"
    )

    @app.post("/api/workbench/sessions")
    def start():
        return {"ok": True}

    app.add_middleware(RateLimiterMiddleware)
    c = TestClient(app)
    assert c.post("/api/workbench/sessions").status_code == 200
    assert c.post("/api/workbench/sessions").status_code == 200
    r = c.post("/api/workbench/sessions")
    assert r.status_code == 429


def test_rate_limiter_high_rate_post_tts_override(monkeypatch):
    """流式 TTS 连续 POST 多句，需高于默认 60/min。"""
    RateLimiterMiddleware, app = _shared_setup_rate_limiter_high_rate_0(
        monkeypatch, case_value_1="2", case_value_2="20"
    )

    @app.post("/api/workbench/tts/edge/stream")
    def tts_stream():
        return {"ok": True}

    app.add_middleware(RateLimiterMiddleware)
    c = TestClient(app)
    for _ in range(15):
        assert c.post("/api/workbench/tts/edge/stream").status_code == 200


def test_rate_limiter_high_rate_market_catalog_override(monkeypatch):
    """AI 市场目录 GET 使用高频只读限额，避免反代共 IP 时误伤 429。"""
    RateLimiterMiddleware, app = _shared_setup_rate_limiter_high_rate_0(
        monkeypatch, case_value_1="2", case_value_2="20"
    )

    @app.get("/api/market/catalog")
    def catalog():
        return {"items": []}

    app.add_middleware(RateLimiterMiddleware)
    c = TestClient(app)
    for _ in range(15):
        assert c.get("/api/market/catalog").status_code == 200


@pytest.mark.parametrize("header", ["X-Forwarded-For", "X-Modstore-User", "X-User-Id"])
def test_rate_limiter_ignores_unverified_identity_headers(monkeypatch, header):
    RateLimiterMiddleware, app = _shared_setup_rate_limiter_high_rate_0(monkeypatch, "1", "1")

    @app.post("/api/auth/login")
    def login():
        return {"ok": True}

    app.add_middleware(RateLimiterMiddleware)
    c = TestClient(app)
    assert c.post("/api/auth/login").status_code == 200
    for value in ("198.51.100.1", "198.51.100.2"):
        response = c.post("/api/auth/login", headers={header: value})
        assert response.status_code == 429
        assert "Retry-After" in response.headers


@pytest.mark.parametrize("trusted_proxy", [True, False])
def test_rate_limiter_uses_only_server_validated_proxy_identity(monkeypatch, trusted_proxy):
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    RateLimiterMiddleware, app = _shared_setup_rate_limiter_high_rate_0(monkeypatch, "1", "1")

    @app.post("/api/auth/login")
    def login():
        return {"ok": True}

    app.add_middleware(RateLimiterMiddleware)
    # Uvicorn, outside the application, resolves the first untrusted hop from
    # the right; nginx appends the real peer after any caller-supplied values.
    c = TestClient(
        ProxyHeadersMiddleware(app, trusted_hosts=["testclient"] if trusted_proxy else [])
    )
    for forwarded, expected in (
        ("203.0.113.1, 198.51.100.1", 200),
        ("203.0.113.2, 198.51.100.1", 429),
        ("203.0.113.3, 198.51.100.2", 200 if trusted_proxy else 429),
        ("203.0.113.4, 198.51.100.2", 429),
    ):
        response = c.post("/api/auth/login", headers={"X-Forwarded-For": forwarded})
        assert response.status_code == expected


def test_rate_limiter_high_rate_limit_floor(monkeypatch):
    """``MODSTORE_RATE_LIMIT_HIGH`` 不允许低于全局 limit；命中时退化为全局值。"""
    RateLimiterMiddleware, app = _shared_setup_rate_limiter_high_rate_0(
        monkeypatch, case_value_1="5", case_value_2="1"
    )

    @app.get("/api/workbench/sessions/{sid}")
    def poll(sid: str):
        return {"id": sid}

    app.add_middleware(RateLimiterMiddleware)
    c = TestClient(app)
    for _ in range(5):
        assert c.get("/api/workbench/sessions/x").status_code == 200
    r = c.get("/api/workbench/sessions/x")
    assert r.status_code == 429
