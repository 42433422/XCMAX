"""SubscriptionGateMiddleware 单元测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.middleware.subscription_gate import SubscriptionGateMiddleware, _subscription_gate_enabled


def _make_request(path: str = "/api/products/list") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "scheme": "http",
        "root_path": "",
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_disabled_passes_through(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("XCAGI_ENFORCE_SUBSCRIPTION", raising=False)
    mw = SubscriptionGateMiddleware(app=MagicMock())
    req = _make_request()
    nxt = AsyncMock(return_value=Response("ok", status_code=200))
    resp = await mw.dispatch(req, nxt)
    assert resp.status_code == 200
    nxt.assert_awaited_once()


@pytest.mark.asyncio
async def test_skip_prefix_auth(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XCAGI_ENFORCE_SUBSCRIPTION", "1")
    mw = SubscriptionGateMiddleware(app=MagicMock())
    req = _make_request("/api/auth/login")
    nxt = AsyncMock(return_value=Response("ok", status_code=200))
    resp = await mw.dispatch(req, nxt)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_non_api_path_passes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XCAGI_ENFORCE_SUBSCRIPTION", "true")
    mw = SubscriptionGateMiddleware(app=MagicMock())
    req = _make_request("/static/app.js")
    nxt = AsyncMock(return_value=Response("ok", status_code=200))
    resp = await mw.dispatch(req, nxt)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_anonymous_user_passes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XCAGI_ENFORCE_SUBSCRIPTION", "yes")
    mw = SubscriptionGateMiddleware(app=MagicMock())
    req = _make_request("/api/orders")
    nxt = AsyncMock(return_value=Response("ok", status_code=200))
    with patch("app.infrastructure.auth.dependencies.resolve_session_user", return_value=None):
        resp = await mw.dispatch(req, nxt)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_active_subscription_passes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XCAGI_ENFORCE_SUBSCRIPTION", "on")
    mw = SubscriptionGateMiddleware(app=MagicMock())
    req = _make_request("/api/orders")
    nxt = AsyncMock(return_value=Response("ok", status_code=200))
    user = MagicMock(id=7)
    with (
        patch("app.infrastructure.auth.dependencies.resolve_session_user", return_value=user),
        patch(
            "app.application.tenant_subscription_app_service.subscription_status_for_user",
            return_value={"active": True},
        ),
    ):
        resp = await mw.dispatch(req, nxt)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_expired_subscription_blocks(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XCAGI_ENFORCE_SUBSCRIPTION", "1")
    mw = SubscriptionGateMiddleware(app=MagicMock())
    req = _make_request("/api/orders")
    nxt = AsyncMock(return_value=Response("ok", status_code=200))
    user = MagicMock(id=9)
    status = {"active": False, "plan": "trial"}
    with (
        patch("app.infrastructure.auth.dependencies.resolve_session_user", return_value=user),
        patch(
            "app.application.tenant_subscription_app_service.subscription_status_for_user",
            return_value=status,
        ),
    ):
        resp = await mw.dispatch(req, nxt)
    assert resp.status_code == 403
    nxt.assert_not_awaited()
    body = resp.body.decode()
    assert "SUBSCRIPTION_REQUIRED" in body


def test_subscription_gate_enabled_truthy_values(monkeypatch: pytest.MonkeyPatch):
    for val in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("XCAGI_ENFORCE_SUBSCRIPTION", val)
        assert _subscription_gate_enabled() is True
    monkeypatch.setenv("XCAGI_ENFORCE_SUBSCRIPTION", "0")
    assert _subscription_gate_enabled() is False
