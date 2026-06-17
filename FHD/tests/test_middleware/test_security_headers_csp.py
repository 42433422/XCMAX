"""COVERAGE_RAMP C3.0: SecurityHeaders 中间件 - 默认 / sandbox / https / 非 http。

覆盖：
- 普通路径：x-content-type-options / x-frame-options / csp 默认值
- ?sandbox=1 或 /xcmax-dashboard 路径：更宽松的 CSP
- https scheme → HSTS
- 非 http scope 透传
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.security_headers import SecurityHeadersMiddleware


def _csp_for(headers: dict) -> bytes:
    return headers.get(b"content-security-policy", b"")


def test_default_security_headers_added():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/api/health")
    def health():
        return {"success": True}

    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers.get("strict-transport-security") is None  # http scheme


def test_desktop_mode_allows_vue_i18n_runtime_compile(monkeypatch):
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/login")
    def login():
        return {"success": True}

    client = TestClient(app)
    r = client.get("/login")
    assert r.status_code == 200
    assert r.headers["x-frame-options"] == "DENY"
    assert "script-src 'self' 'unsafe-inline' 'unsafe-eval'" in r.headers[
        "content-security-policy"
    ]


def test_sandbox_query_param_relaxes_csp():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/api/health")
    def health():
        return {"success": True}

    client = TestClient(app)
    r = client.get("/api/health?sandbox=1")
    csp = r.headers["content-security-policy"]
    # sandbox CSP 没有 frame-ancestors 'self' 限制（但其实仍然保留），关键是 'unsafe-inline' / 'unsafe-eval'
    assert "unsafe-inline" in csp
    assert "unsafe-eval" in csp
    assert r.headers.get("x-frame-options") is None  # sandbox 不加 DENY


def test_xcmax_dashboard_path_relaxes_csp():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/xcmax-dashboard/page")
    def page():
        return {"success": True}

    client = TestClient(app)
    r = client.get("/xcmax-dashboard/page")
    csp = r.headers["content-security-policy"]
    assert "unsafe-inline" in csp
    # dashboard embed CSP 允许 Google Fonts（不再依赖 cdn.jsdelivr.net）
    assert "fonts.googleapis.com" in csp
    assert "frame-ancestors 'self'" in csp


def test_https_scheme_adds_hsts():
    """TestClient 默认 http，验证 https 走 middleware 内部逻辑添加 HSTS。"""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/api/health")
    def health():
        return {"success": True}

    # 通过直接构造 scope 来测试
    captured = {}

    async def downstream_app(scope, receive, send):
        captured["scheme"] = scope.get("scheme")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    wrapped = SecurityHeadersMiddleware(downstream_app)

    async def receive():
        return {"type": "http.request", "body": b""}

    sent = []

    async def send(msg):
        sent.append(msg)

    asyncio.run(
        wrapped(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/health",
                "scheme": "https",
                "headers": [],
            },
            receive,
            send,
        )
    )
    headers = dict(sent[0]["headers"])
    assert headers[b"strict-transport-security"] == b"max-age=31536000; includeSubDomains"
    assert headers[b"x-content-type-options"] == b"nosniff"


def test_non_http_scope_passthrough():
    captured = []

    async def downstream(scope, receive, send):
        captured.append(scope["type"])
        await send({"type": "websocket.accept"})

    wrapped = SecurityHeadersMiddleware(downstream)
    sent = []

    async def receive():
        return {"type": "websocket.connect"}

    async def send(msg):
        sent.append(msg)

    asyncio.run(wrapped({"type": "websocket", "path": "/ws"}, receive, send))
    assert captured == ["websocket"]
    assert sent[0]["type"] == "websocket.accept"
