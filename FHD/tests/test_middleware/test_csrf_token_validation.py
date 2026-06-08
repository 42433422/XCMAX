"""COVERAGE_RAMP C3.0: CSRF 中间件 - safe/mutating/exception/sandbox 路径。

覆盖：
- 安全方法（GET/HEAD/OPTIONS）放行
- mutating 方法缺 csrf cookie → 403
- mutating 方法 cookie 与 header 不匹配 → 403
- mutating 方法 token 一致 → 放行
- 登录/登出 默认豁免
- XCAGI_CSRF_EXEMPT_AUTH=0 → 登录仍校验
- /api/mod-store/install 在 sandbox 实例下豁免
- 非 http scope 透传
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.csrf import CSRFMiddleware


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("XCAGI_CSRF_EXEMPT_AUTH", raising=False)
    monkeypatch.delenv("XCAGI_SANDBOX_INSTANCE", raising=False)
    yield


@pytest.fixture
def client():
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.get("/api/items")
    def items():
        return {"success": True}

    @app.post("/api/items")
    def create_item():
        return {"success": True, "created": True}

    @app.post("/api/auth/login")
    def login():
        return {"success": True}

    @app.post("/api/auth/logout")
    def logout():
        return {"success": True}

    @app.post("/api/mod-store/install")
    def install():
        return {"success": True}

    return TestClient(app, raise_server_exceptions=False)


def test_safe_method_no_csrf_required(client):
    r = client.get("/api/items")
    assert r.status_code == 200


def test_mutating_missing_csrf_cookie_rejected(client):
    r = client.post("/api/items")
    assert r.status_code == 403


def test_mutating_cookie_header_mismatch_rejected(client):
    r = client.post(
        "/api/items",
        headers={"X-CSRF-Token": "header-tok"},
        cookies={"csrf_token": "cookie-tok"},
    )
    assert r.status_code == 403


def test_mutating_matching_csrf_allowed(client):
    r = client.post(
        "/api/items",
        headers={"X-CSRF-Token": "same-tok"},
        cookies={"csrf_token": "same-tok"},
    )
    assert r.status_code == 200
    assert r.json() == {"success": True, "created": True}


def test_login_exempt_by_default(client):
    """登录默认豁免（XCAGI_CSRF_EXEMPT_AUTH 未设时）。"""
    r = client.post("/api/auth/login")
    assert r.status_code == 200


def test_logout_exempt_by_default(client):
    r = client.post("/api/auth/logout")
    assert r.status_code == 200


def test_login_not_exempt_when_env_disables(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XCAGI_CSRF_EXEMPT_AUTH", "0")
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.post("/api/auth/login")
    def login():
        return {"success": True}

    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/api/auth/login")
    assert r.status_code == 403


def test_logout_not_exempt_when_env_disables(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XCAGI_CSRF_EXEMPT_AUTH", "0")
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.post("/api/auth/logout")
    def logout():
        return {"success": True}

    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/api/auth/logout")
    assert r.status_code == 403


def test_sandbox_modstore_install_exempt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XCAGI_SANDBOX_INSTANCE", "1")
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.post("/api/mod-store/install")
    def install():
        return {"success": True}

    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/api/mod-store/install")
    assert r.status_code == 200


def test_sandbox_other_endpoint_still_requires_csrf(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XCAGI_SANDBOX_INSTANCE", "1")
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.post("/api/mod-store/publish")
    def publish():
        return {"success": True}

    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/api/mod-store/publish")
    assert r.status_code == 403


def test_non_http_scope_passthrough():
    """WebSocket / lifespan 等非 http scope 直接放行。"""

    async def app(scope, receive, send):
        assert scope["type"] == "websocket"
        await send({"type": "websocket.accept"})

    wrapped = CSRFMiddleware(app)
    import asyncio

    received = []

    async def receive():
        return {"type": "websocket.connect"}

    async def send(msg):
        received.append(msg)

    asyncio.run(wrapped({"type": "websocket", "path": "/ws"}, receive, send))
    assert received and received[0]["type"] == "websocket.accept"
