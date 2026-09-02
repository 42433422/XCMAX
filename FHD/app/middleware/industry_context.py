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
from starlette.responses import JSONResponse, Response

from app.infrastructure.request_context import (
    reset_current_request,
    set_current_request,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

DEFAULT_INDUSTRY = "通用"
ADMIN_INDUSTRY = "管理端"


def _expire_tutorial_cookie(response: Response) -> Response:
    """Remove an unusable teaching cookie without exposing or replaying it."""
    from app.application.tutorial_v2.scope import TUTORIAL_COOKIE

    response.delete_cookie(TUTORIAL_COOKIE, path="/", httponly=True, samesite="strict")
    return response


def _tutorial_error(code: str, hint: str, status_code: int, *, clear_cookie: bool) -> Response:
    response = JSONResponse(
        {"success": False, "error": {"code": code, "hint": hint}},
        status_code=status_code,
    )
    return _expire_tutorial_cookie(response) if clear_cookie else response


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
        if isinstance(user, dict):
            tier = str(user.get("tier") or "").strip()
            username = str(user.get("username") or "").strip()
            industry_id = str(user.get("industry_id") or "").strip()
        else:
            tier = str(getattr(user, "tier", "") or "").strip()
            username = str(getattr(user, "username", "") or "").strip()
            industry_id = str(getattr(user, "industry_id", "") or "").strip()
        if tier == "admin":
            return ADMIN_INDUSTRY
        from app.mod_sdk.customer_delivery import industry_id_for_account

        delivery_industry = industry_id_for_account(username)
        if delivery_industry:
            return delivery_industry
        return industry_id or DEFAULT_INDUSTRY
    except RECOVERABLE_ERRORS:
        return DEFAULT_INDUSTRY


def _resolve_tenant_id(user: Any | None) -> int | None:
    """从已解析用户派生租户 id（业务数据隔离作用域；零额外查询）。"""
    if user is None:
        return None
    try:
        tid = getattr(user, "tenant_id", None)
        return int(tid) if tid is not None else None
    except (TypeError, ValueError, AttributeError):
        return None


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
                tenant_id = _resolve_tenant_id(user)
            except RECOVERABLE_ERRORS:
                industry_id = DEFAULT_INDUSTRY
                tenant_id = None
            request.state.industry_id = industry_id
            request.state.source_tenant_id = tenant_id
            request.state.tenant_id = tenant_id
            request.state.tutorial_active = False
            tutorial_cookie = str(request.cookies.get("xcagi_tutorial_run") or "").strip()
            if tutorial_cookie:
                from app.application.tutorial_v2.scope import is_tutorial_recovery_path

                accepts_html = "text/html" in str(request.headers.get("accept") or "").lower()
                browser_navigation = request.method.upper() == "GET" and accepts_html
                recovery_path = is_tutorial_recovery_path(request.url.path) or browser_navigation
                if user is None or tenant_id is None or getattr(user, "id", None) is None:
                    if recovery_path:
                        return _expire_tutorial_cookie(await call_next(request))
                    return _tutorial_error(
                        "tutorial_cookie_invalid",
                        "教学会话已失效，已为你退出教学空间；请重新登录后进入教程。",
                        401,
                        clear_cookie=True,
                    )
                try:
                    from app.application.tutorial_v2.scope import resolve_tutorial_scope
                    from app.db import SessionLocal

                    db = SessionLocal()
                    try:
                        decision = resolve_tutorial_scope(
                            db,
                            request,
                            user_id=int(user.id),
                            source_tenant_id=int(tenant_id),
                        )
                    finally:
                        db.close()
                except RECOVERABLE_ERRORS:
                    logger.warning("tutorial scope resolution failed")
                    return _tutorial_error(
                        "tutorial_scope_unavailable",
                        "教学空间暂时不可用，请保存退出后重试。",
                        503,
                        clear_cookie=False,
                    )
                if decision.error_code:
                    stale = decision.error_code in {
                        "tutorial_cookie_invalid",
                        "tutorial_cookie_expired",
                    }
                    if stale and recovery_path:
                        return _expire_tutorial_cookie(await call_next(request))
                    return _tutorial_error(
                        decision.error_code,
                        str(decision.error_hint or "教学会话不可用，请重新进入教程。"),
                        decision.error_status,
                        clear_cookie=stale,
                    )
                request.state.tutorial_active = decision.active
                request.state.tutorial_run_id = decision.run_id
                request.state.tutorial_workspace_id = decision.workspace_id
                request.state.tutorial_course_id = decision.course_id
                request.state.tutorial_tenant_id = decision.tutorial_tenant_id
                if decision.switched:
                    request.state.tenant_id = decision.tutorial_tenant_id
            return await call_next(request)
        finally:
            reset_current_request(token)


__all__ = [
    "ADMIN_INDUSTRY",
    "DEFAULT_INDUSTRY",
    "IndustryContextMiddleware",
    "get_current_user",
]
