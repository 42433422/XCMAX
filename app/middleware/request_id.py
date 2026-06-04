# -*- coding: utf-8 -*-
"""为每个 HTTP 请求分配或透传 X-Request-ID。"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class RequestIdMiddleware(BaseHTTPMiddleware):
    """透传客户端 X-Request-ID，否则生成 UUID，并在响应头中带回。"""

    async def dispatch(self, request: Request, call_next):
        incoming = (request.headers.get("x-request-id") or "").strip()
        request_id = incoming or str(uuid.uuid4())
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
