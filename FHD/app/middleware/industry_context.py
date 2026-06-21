"""行业上下文中间件：每请求从 User.industry_id 派生行业并注入 request.state。

设计目标：
- 每请求读取认证用户的 industry_id，注入 ``request.state.industry_id``
- 未认证用户默认 ``"通用"``
- admin 用户（tier == "admin"）注入 ``"管理端"``（与 planner_compat_service 派生逻辑一致）
- 永不阻断请求：任何异常都回退到 ``"通用"``

同时把当前请求设置到 ContextVar，供无 Request 参数的旧代码路径
（如 value_objects_industry.get_current_industry）读取。
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.infrastructure.request_context import (
    reset_current_request,
    set_current_request,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

DEFAULT_INDUSTRY = "通用"
ADMIN_INDUSTRY = "管理端"


def get_current_user(request: Request) -> Any | None:
    """复用现有认证逻辑解析当前用户。

    包装 ``resolve_session_user``，异常时返回 None（不阻断请求）。
    """
    try:
        from app.infrastructure.auth.dependencies import resolve_session_user

        return resolve_session_user(request)
    except RECOVERABLE_ERRORS:
        logger.debug("industry_context: resolve_session_user failed", exc_info=True)
        return None


def _resolve_industry_id(user: Any | None) -> str:
    """从用户对象派生行业 id。"""
    if user is None:
        return DEFAULT_INDUSTRY
    try:
        tier = str(getattr(user, "tier", "") or "").strip()
        if tier == "admin":
            return ADMIN_INDUSTRY
        industry_id = str(getattr(user, "industry_id", "") or "").strip()
        return industry_id or DEFAULT_INDUSTRY
    except RECOVERABLE_ERRORS:
        return DEFAULT_INDUSTRY


class IndustryContextMiddleware(BaseHTTPMiddleware):
    """每请求注入 ``request.state.industry_id`` 并设置请求 ContextVar。"""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        token = set_current_request(request)
        try:
            try:
                user = get_current_user(request)
                industry_id = _resolve_industry_id(user)
            except RECOVERABLE_ERRORS:
                industry_id = DEFAULT_INDUSTRY
            request.state.industry_id = industry_id
            return await call_next(request)
        finally:
            reset_current_request(token)


__all__ = [
    "ADMIN_INDUSTRY",
    "DEFAULT_INDUSTRY",
    "IndustryContextMiddleware",
    "get_current_user",
]
