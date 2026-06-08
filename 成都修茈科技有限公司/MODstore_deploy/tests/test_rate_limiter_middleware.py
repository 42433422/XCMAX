"""RateLimiterMiddleware 挂载与豁免路径行为。"""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

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
    monkeypatch.setenv("MODSTORE_RATE_LIMIT", "2")
    monkeypatch.setenv("MODSTORE_RATE_LIMIT_HIGH", "20")
    monkeypatch.setenv("MODSTORE_RATE_WINDOW", "60")
    monkeypatch.delenv("MODSTORE_REDIS_URL", raising=False)

    from modstore_server.api.rate_limiter import RateLimiterMiddleware

    app = FastAPI()

    @app.get("/api/workbench/sessions/{sid}")
    def poll(sid: str):
        return {"id": sid}

    app.add_middleware(RateLimiterMiddleware)
    c = TestClient(app)
    for _ in range(15):
        assert c.get("/api/workbench/sessions/abc").status_code == 200


def test_rate_limiter_high_rate_override_does_not_apply_to_post(monkeypatch):
    """启动会话（POST /api/workbench/sessions）属于昂贵写入，仍走全局限额。"""
    monkeypatch.setenv("MODSTORE_RATE_LIMIT", "2")
    monkeypatch.setenv("MODSTORE_RATE_LIMIT_HIGH", "200")
    monkeypatch.setenv("MODSTORE_RATE_WINDOW", "60")
    monkeypatch.delenv("MODSTORE_REDIS_URL", raising=False)

    from modstore_server.api.rate_limiter import RateLimiterMiddleware

    app = FastAPI()

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
    monkeypatch.setenv("MODSTORE_RATE_LIMIT", "2")
    monkeypatch.setenv("MODSTORE_RATE_LIMIT_HIGH", "20")
    monkeypatch.setenv("MODSTORE_RATE_WINDOW", "60")
    monkeypatch.delenv("MODSTORE_REDIS_URL", raising=False)

    from modstore_server.api.rate_limiter import RateLimiterMiddleware

    app = FastAPI()

    @app.post("/api/workbench/tts/edge/stream")
    def tts_stream():
        return {"ok": True}

    app.add_middleware(RateLimiterMiddleware)
    c = TestClient(app)
    for _ in range(15):
        assert c.post("/api/workbench/tts/edge/stream").status_code == 200


def test_rate_limiter_high_rate_market_catalog_override(monkeypatch):
    """AI 市场目录 GET 使用高频只读限额，避免反代共 IP 时误伤 429。"""
    monkeypatch.setenv("MODSTORE_RATE_LIMIT", "2")
    monkeypatch.setenv("MODSTORE_RATE_LIMIT_HIGH", "20")
    monkeypatch.setenv("MODSTORE_RATE_WINDOW", "60")
    monkeypatch.delenv("MODSTORE_REDIS_URL", raising=False)

    from modstore_server.api.rate_limiter import RateLimiterMiddleware

    app = FastAPI()

    @app.get("/api/market/catalog")
    def catalog():
        return {"items": []}

    app.add_middleware(RateLimiterMiddleware)
    c = TestClient(app)
    for _ in range(15):
        assert c.get("/api/market/catalog").status_code == 200


def test_rate_limiter_uses_x_forwarded_for(monkeypatch):
    monkeypatch.setenv("MODSTORE_RATE_LIMIT", "1")
    monkeypatch.setenv("MODSTORE_RATE_WINDOW", "60")
    monkeypatch.delenv("MODSTORE_REDIS_URL", raising=False)

    from modstore_server.api.rate_limiter import RateLimiterMiddleware

    app = FastAPI()

    @app.get("/hit")
    def hit():
        return {"ok": True}

    app.add_middleware(RateLimiterMiddleware)
    c = TestClient(app)
    assert c.get("/hit", headers={"X-Forwarded-For": "1.2.3.4"}).status_code == 200
    assert c.get("/hit", headers={"X-Forwarded-For": "5.6.7.8"}).status_code == 200
    assert c.get("/hit", headers={"X-Forwarded-For": "1.2.3.4"}).status_code == 429


def test_rate_limiter_high_rate_limit_floor(monkeypatch):
    """``MODSTORE_RATE_LIMIT_HIGH`` 不允许低于全局 limit；命中时退化为全局值。"""
    monkeypatch.setenv("MODSTORE_RATE_LIMIT", "5")
    monkeypatch.setenv("MODSTORE_RATE_LIMIT_HIGH", "1")
    monkeypatch.setenv("MODSTORE_RATE_WINDOW", "60")
    monkeypatch.delenv("MODSTORE_REDIS_URL", raising=False)

    from modstore_server.api.rate_limiter import RateLimiterMiddleware

    app = FastAPI()

    @app.get("/api/workbench/sessions/{sid}")
    def poll(sid: str):
        return {"id": sid}

    app.add_middleware(RateLimiterMiddleware)
    c = TestClient(app)
    for _ in range(5):
        assert c.get("/api/workbench/sessions/x").status_code == 200
    r = c.get("/api/workbench/sessions/x")
    assert r.status_code == 429
