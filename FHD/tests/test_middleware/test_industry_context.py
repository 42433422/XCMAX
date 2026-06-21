"""app/middleware/industry_context 单测：行业上下文注入。

直接驱动 dispatch（fake request + fake call_next），不起真实 ASGI（铁律4）。
覆盖：认证用户注入 / 未认证用户默认 / admin 用户注入管理端（铁律3）。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from starlette.requests import Request
from starlette.responses import Response

from app.middleware.industry_context import (
    ADMIN_INDUSTRY,
    DEFAULT_INDUSTRY,
    IndustryContextMiddleware,
)


def _make_request(headers: dict[str, str] | None = None) -> Request:
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": raw_headers,
        "query_string": b"",
        "state": {},
    }
    return Request(scope)


async def _call_next(_request: Request) -> Response:
    return Response("ok")


def _middleware() -> IndustryContextMiddleware:
    async def _app(_scope, _receive, _send):  # pragma: no cover - 不经 ASGI 路径
        return None

    return IndustryContextMiddleware(_app)


async def test_authenticated_user_injects_industry_id():
    """认证用户：request.state.industry_id 应为用户的 industry_id。"""
    mw = _middleware()
    req = _make_request()
    fake_user = SimpleNamespace(id=1, tier="personal", industry_id="涂料")

    with patch("app.middleware.industry_context.get_current_user", return_value=fake_user):
        resp = await mw.dispatch(req, _call_next)

    assert resp.status_code == 200
    assert req.state.industry_id == "涂料"


async def test_unauthenticated_user_defaults_to_general():
    """未认证用户：request.state.industry_id 应为默认值 "通用"。"""
    mw = _middleware()
    req = _make_request()

    with patch("app.middleware.industry_context.get_current_user", return_value=None):
        resp = await mw.dispatch(req, _call_next)

    assert resp.status_code == 200
    assert req.state.industry_id == DEFAULT_INDUSTRY


async def test_admin_user_injects_admin_industry():
    """admin 用户（tier == "admin"）：request.state.industry_id 应为 "管理端"。"""
    mw = _middleware()
    req = _make_request()
    fake_admin = SimpleNamespace(id=2, tier="admin", industry_id="通用")

    with patch("app.middleware.industry_context.get_current_user", return_value=fake_admin):
        resp = await mw.dispatch(req, _call_next)

    assert resp.status_code == 200
    assert req.state.industry_id == ADMIN_INDUSTRY


async def test_resolve_session_user_exception_falls_back_to_general():
    """resolve_session_user 抛异常时回退到 "通用"，不阻断请求。"""
    mw = _middleware()
    req = _make_request()

    with patch(
        "app.middleware.industry_context.get_current_user", side_effect=RuntimeError("boom")
    ):
        resp = await mw.dispatch(req, _call_next)

    assert resp.status_code == 200
    assert req.state.industry_id == DEFAULT_INDUSTRY


async def test_user_with_empty_industry_id_falls_back_to_general():
    """认证用户但 industry_id 为空时回退到 "通用"。"""
    mw = _middleware()
    req = _make_request()
    fake_user = SimpleNamespace(id=3, tier="personal", industry_id="")

    with patch("app.middleware.industry_context.get_current_user", return_value=fake_user):
        resp = await mw.dispatch(req, _call_next)

    assert resp.status_code == 200
    assert req.state.industry_id == DEFAULT_INDUSTRY
