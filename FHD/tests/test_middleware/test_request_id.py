"""app/middleware/request_id 单测：X-Request-ID 透传/生成。

直接驱动 dispatch（fake request + fake call_next），不起真实 ASGI（铁律4）。
覆盖：带头透传 / 缺头生成 / 空白头生成（铁律3）。
"""

from __future__ import annotations

import uuid

from starlette.requests import Request
from starlette.responses import Response

from app.middleware.request_id import RequestIdMiddleware


def _make_request(headers: dict[str, str]) -> Request:
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
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


def _middleware() -> RequestIdMiddleware:
    async def _app(_scope, _receive, _send):  # pragma: no cover - 不经 ASGI 路径
        return None

    return RequestIdMiddleware(_app)


async def test_passthrough_existing_request_id():
    mw = _middleware()
    req = _make_request({"X-Request-ID": "fixed-123"})
    resp = await mw.dispatch(req, _call_next)
    assert req.state.request_id == "fixed-123"
    assert resp.headers["X-Request-ID"] == "fixed-123"


async def test_generates_uuid_when_missing():
    mw = _middleware()
    req = _make_request({})
    resp = await mw.dispatch(req, _call_next)
    generated = resp.headers["X-Request-ID"]
    # 不抛即为合法 UUID
    uuid.UUID(generated)
    assert req.state.request_id == generated


async def test_generates_uuid_when_blank():
    mw = _middleware()
    req = _make_request({"X-Request-ID": "   "})
    resp = await mw.dispatch(req, _call_next)
    generated = resp.headers["X-Request-ID"]
    uuid.UUID(generated)
    assert generated.strip() != ""
