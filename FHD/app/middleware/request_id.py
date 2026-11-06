"""X-Request-ID 透传 / 生成中间件。"""

from __future__ import annotations

import re
import uuid
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{8,80}$")


def normalize_request_id(raw: str | None) -> str:
    """只接受短的可见标识。空值、换行和过长值都换成新的 id，避免日志注入。"""
    text = (raw or "").strip()
    if _SAFE_REQUEST_ID.fullmatch(text):
        return text
    return uuid.uuid4().hex


def ensure_request_id(request: Request) -> str:
    current = str(getattr(request.state, "request_id", "") or "")
    if _SAFE_REQUEST_ID.fullmatch(current):
        return current
    request_id = normalize_request_id(request.headers.get("X-Request-ID"))
    request.state.request_id = request_id
    return request_id


class RequestIdMiddleware(BaseHTTPMiddleware):
    """未带或非法 X-Request-ID 时生成 id；写入 request.state 与响应头。"""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.request_id = normalize_request_id(request.headers.get("X-Request-ID"))
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response


__all__ = ["RequestIdMiddleware"]
