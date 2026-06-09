"""HTTP 全局限流与认证路径专用限流。"""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.auth_rate_limit import AuthRateLimitMiddleware
from app.middleware.global_rate_limit import GlobalRateLimitMiddleware
from app.utils import rate_limiter as rate_limiter_mod


@pytest.fixture(autouse=True)
def _reset_rate_limiter_state(monkeypatch):
    monkeypatch.delenv("CACHE_REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("XCAGI_REDIS_URL", raising=False)
    rate_limiter_mod._redis_client = None
    rate_limiter_mod._redis_init_attempted = False
    rate_limiter_mod._rate_limiters.clear()
    rate_limiter_mod._circuit_breakers.clear()
    yield
    rate_limiter_mod._redis_client = None
    rate_limiter_mod._redis_init_attempted = False
    rate_limiter_mod._rate_limiters.clear()
    rate_limiter_mod._circuit_breakers.clear()


@pytest.fixture
def rate_limit_app():
    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"success": True}

    @app.post("/api/auth/login")
    def login():
        return {"success": True}

    @app.get("/api/other/ping")
    def ping():
        return {"success": True}

    app.add_middleware(GlobalRateLimitMiddleware)
    app.add_middleware(AuthRateLimitMiddleware)
    return app


def test_auth_rate_limit_returns_429(monkeypatch, rate_limit_app):
    monkeypatch.setenv("XCAGI_AUTH_RATE_LIMIT", "1")
    monkeypatch.setenv("XCAGI_AUTH_RATE_LIMIT_MAX", "2")
    monkeypatch.setenv("XCAGI_AUTH_RATE_LIMIT_WINDOW", "60")
    monkeypatch.setenv("XCAGI_GLOBAL_RATE_LIMIT", "0")
    monkeypatch.setenv("CACHE_REDIS_URL", "")
    client = TestClient(rate_limit_app)
    for _ in range(2):
        r = client.post("/api/auth/login", json={"username": "a", "password": "b"})
        assert r.status_code == 200
    r3 = client.post("/api/auth/login", json={"username": "a", "password": "b"})
    assert r3.status_code == 429
    body = r3.json()
    assert body.get("code") == "RATE_LIMITED"


def test_global_rate_limit_returns_429(monkeypatch, rate_limit_app):
    monkeypatch.setenv("XCAGI_AUTH_RATE_LIMIT", "0")
    monkeypatch.setenv("XCAGI_GLOBAL_RATE_LIMIT", "1")
    monkeypatch.setenv("XCAGI_GLOBAL_RATE_LIMIT_MAX", "2")
    monkeypatch.setenv("XCAGI_GLOBAL_RATE_LIMIT_WINDOW", "60")
    monkeypatch.setenv("CACHE_REDIS_URL", "")
    client = TestClient(rate_limit_app)
    for _ in range(2):
        assert client.get("/api/other/ping").status_code == 200
    r = client.get("/api/other/ping")
    assert r.status_code == 429
    assert r.json().get("code") == "RATE_LIMITED"
