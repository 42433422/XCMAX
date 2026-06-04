"""全局 MFA 强制：XCAGI_MFA_REQUIRED=1 时已登录用户须已绑定 TOTP。"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_EXEMPT_PREFIXES = (
    "/api/health",
    "/api/ping",
    "/health/",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/oidc/",
    "/api/auth/saml/",
    "/api/auth/mfa/enroll",
    "/api/auth/mfa/enroll-self",
    "/api/auth/session/validate",
)


class MfaRequiredMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        from app.infrastructure.auth.mfa_totp import mfa_required_globally

        if not mfa_required_globally():
            return await call_next(request)

        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

        from app.infrastructure.auth.dependencies import resolve_session_user

        user = resolve_session_user(request)
        if user is None:
            return await call_next(request)

        if getattr(user, "totp_secret", None):
            return await call_next(request)

        return JSONResponse(
            status_code=403,
            content={
                "success": False,
                "error": {
                    "code": "MFA_ENROLLMENT_REQUIRED",
                    "message": "请先调用 POST /api/auth/mfa/enroll-self 绑定 TOTP",
                },
            },
        )
