"""app/middleware/security_headers 单测：CSP / HSTS 分支。"""

from __future__ import annotations

import pytest

from app.middleware.security_headers import SecurityHeadersMiddleware


@pytest.mark.asyncio
async def test_default_security_headers_on_http():
    captured: list[dict] = []

    async def inner_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    mw = SecurityHeadersMiddleware(inner_app)

    async def send(message):
        captured.append(message)

    scope = {
        "type": "http",
        "scheme": "http",
        "path": "/api/health",
        "query_string": b"",
    }

    await mw(scope, lambda: None, send)
    start = captured[0]
    hdrs = dict(start["headers"])
    assert hdrs[b"x-frame-options"] == b"DENY"
    assert b"strict-transport-security" not in hdrs


@pytest.mark.asyncio
async def test_https_adds_hsts():
    captured: list[dict] = []

    async def inner_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    mw = SecurityHeadersMiddleware(inner_app)

    async def send(message):
        captured.append(message)

    scope = {"type": "http", "scheme": "https", "path": "/", "query_string": b""}
    await mw(scope, lambda: None, send)
    hdrs = dict(captured[0]["headers"])
    assert b"strict-transport-security" in hdrs


@pytest.mark.asyncio
async def test_sandbox_relaxed_csp():
    captured: list[dict] = []

    async def inner_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    mw = SecurityHeadersMiddleware(inner_app)

    async def send(message):
        captured.append(message)

    scope = {
        "type": "http",
        "scheme": "http",
        "path": "/",
        "query_string": b"sandbox=1",
    }
    await mw(scope, lambda: None, send)
    hdrs = dict(captured[0]["headers"])
    assert b"frame-ancestors *" in hdrs[b"content-security-policy"]


@pytest.mark.asyncio
async def test_dashboard_embed_csp():
    captured: list[dict] = []

    async def inner_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    mw = SecurityHeadersMiddleware(inner_app)

    async def send(message):
        captured.append(message)

    scope = {
        "type": "http",
        "scheme": "http",
        "path": "/xcmax-dashboard/foo",
        "query_string": b"",
    }
    await mw(scope, lambda: None, send)
    hdrs = dict(captured[0]["headers"])
    assert hdrs[b"x-frame-options"] == b"SAMEORIGIN"


@pytest.mark.asyncio
async def test_non_http_passthrough():
    called = {"inner": False}

    async def inner_app(scope, receive, send):
        called["inner"] = True

    mw = SecurityHeadersMiddleware(inner_app)
    await mw({"type": "websocket"}, lambda: None, lambda m: None)
    assert called["inner"] is True
