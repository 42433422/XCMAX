"""按请求注入当前租户上下文（纯 ASGI 实现，避免 ``BaseHTTPMiddleware`` 流式问题）。

从会话解析 ``user.tenant_id`` 写入 ContextVar，供全局 ORM 租户过滤使用。
解析失败 / 无租户（平台管理员、未登录、桌面单租户）→ 不设置 → 过滤 no-op。
"""

from __future__ import annotations

from starlette.requests import Request as StarletteRequest
from starlette.types import ASGIApp, Receive, Scope, Send

from app.request_tenant_ctx import reset_request_tenant_id, set_request_tenant_id
from app.utils.operational_errors import RECOVERABLE_ERRORS


class TenantContextMiddleware:
    """与 ``ModContextMiddleware`` 同构：每请求解析租户并设入 ContextVar。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        token = None
        try:
            request = StarletteRequest(scope, receive)
            tid = None
            try:
                from app.infrastructure.auth.tenant_context import resolve_tenant_id

                tid = resolve_tenant_id(request)
            except RECOVERABLE_ERRORS:
                tid = None
            if tid is not None:
                token = set_request_tenant_id(tid)
            await self.app(scope, receive, send)
        finally:
            if token is not None:
                reset_request_tenant_id(token)
