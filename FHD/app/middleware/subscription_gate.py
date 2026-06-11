"""试用到期订阅门禁（可选，XCAGI_ENFORCE_SUBSCRIPTION=1 启用）。"""

from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_SKIP_PREFIXES = (
    "/api/auth/",
    "/api/health",
    "/api/model-payment/",
    # AIOPEN 开放平台：外部 AI Agent 无登录态，安全由 X-AIOPEN-Key 承担
    "/api/aiopen/",
    "/api/market/",
    "/api/app/",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/static/",
    "/ws/",
)


def _subscription_gate_enabled() -> bool:
    return os.environ.get("XCAGI_ENFORCE_SUBSCRIPTION", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


class SubscriptionGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if not _subscription_gate_enabled():
            return await call_next(request)

        path = request.url.path or ""
        if not path.startswith("/api/"):
            return await call_next(request)
        if any(path.startswith(prefix) for prefix in _SKIP_PREFIXES):
            return await call_next(request)

        from app.application.tenant_subscription_app_service import subscription_status_for_user
        from app.infrastructure.auth.dependencies import resolve_session_user

        user = resolve_session_user(request)
        if user is None:
            return await call_next(request)

        status = subscription_status_for_user(int(user.id))
        if status.get("active"):
            return await call_next(request)

        return JSONResponse(
            {
                "success": False,
                "error": {
                    "code": "SUBSCRIPTION_REQUIRED",
                    "message": "试用已结束，请升级套餐后继续使用",
                },
                "data": status,
            },
            status_code=403,
        )
