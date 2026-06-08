"""X-Request-ID 透传 / 生成中间件。"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestIdMiddleware(BaseHTTPMiddleware):
    """未带或非空 X-Request-ID 时生成 UUID；写入 request.state 与响应头。"""

    async def dispatch(self, request: Request, call_next) -> Response:
        raw = (request.headers.get("X-Request-ID") or "").strip()
        request_id = raw or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


__all__ = ["RequestIdMiddleware"]
