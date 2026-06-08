from __future__ import annotations

import os

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from xcagi_common.csrf import (
    MUTATING_HTTP_METHODS,
    SAFE_HTTP_METHODS,
    csrf_tokens_match,
    generate_csrf_token,
)

# 匿名即可调用的认证入口：无法要求「先 GET 再带 X-CSRF-Token」（首跳即登录页时常见）。
_CSRF_EXEMPT_PATHS = frozenset(
    {
        "/api/auth/login",
        "/api/auth/register",
        "/api/auth/login-with-code",
        "/api/auth/login-with-phone-code",
        "/api/auth/send-phone-code",
        "/api/auth/send-code",
        "/api/auth/send-register-code",
        "/api/auth/send-reset-password-code",
        "/api/auth/reset-password",
        "/api/auth/refresh",
        "/api/auth/verify-admin-digest-code",
        # 运维密钥接口：无用户 Cookie 场景（脚本 / TestClient），由 X-Modstore-Recharge-Token 单独鉴权
        "/api/admin/reset-user-password",
        "/api/csp-report",
        "/api/agent/butler/corp-chat",
        "/api/agent/butler/corp-intake-fill",
    }
)

# 前缀豁免：QQ 官方机器人 V2 的 webhook 由 QQ 官方主动 POST，签名头是
# Ed25519，没有 CSRF Cookie 概念。涵盖：
#   - /api/agent/butler/qq/webhook                           （管家默认）
#   - /api/agent/butler/qq/{webhook_key}/webhook             （task-router / employee-interview 等老员工）
#   - /api/agent/butler/qq/by-employee/{employee_id}/webhook （新员工通用入口）
_CSRF_EXEMPT_PREFIXES: tuple[str, ...] = ("/api/agent/butler/qq/",)


def _csrf_exempt_path(path: str) -> bool:
    raw = (path or "").split("?", 1)[0]
    p = raw.rstrip("/") or "/"
    if p in {x.rstrip("/") or "/" for x in _CSRF_EXEMPT_PATHS}:
        return True
    for prefix in _CSRF_EXEMPT_PREFIXES:
        if (raw + "").startswith(prefix) and raw.endswith("/webhook"):
            return True
    return False


def _csrf_disabled_for_tests() -> bool:
    """仅用于自动化测试（``conftest`` 设置 ``MODSTORE_DISABLE_CSRF=1``）；生产环境禁止开启。"""
    return (os.environ.get("MODSTORE_DISABLE_CSRF") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


class CSRFMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive, send)
        if _csrf_disabled_for_tests():
            await self.app(scope, receive, send)
            return

        method = request.method.upper()

        if method in ("GET", "HEAD", "OPTIONS"):
            csrf_cookie = request.cookies.get("csrf_token")
            if not csrf_cookie:
                await self._set_csrf_cookie(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return

        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            await self.app(scope, receive, send)
            return

        if _csrf_exempt_path(request.url.path):
            await self.app(scope, receive, send)
            return

        csrf_cookie = request.cookies.get("csrf_token")
        csrf_header = request.headers.get("x-csrf-token", "")

        if not csrf_cookie or not csrf_header:
            response = JSONResponse({"detail": "CSRF token missing"}, status_code=403)
            await response(scope, receive, send)
            return

        if not csrf_tokens_match(csrf_header, csrf_cookie):
            response = JSONResponse({"detail": "CSRF token mismatch"}, status_code=403)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

    async def _set_csrf_cookie(self, scope, receive, send):
        token = generate_csrf_token()
        # 双提交 Cookie：须允许前端 JS 读取并回传 X-CSRF-Token，故不能 HttpOnly。
        secure = os.environ.get("MODSTORE_ENV", "development").lower() == "production"
        raw_sec = os.environ.get("MODSTORE_CSRF_COOKIE_SECURE", "").strip().lower()
        if raw_sec in ("1", "true", "yes", "on"):
            secure = True
        elif raw_sec in ("0", "false", "no", "off"):
            secure = False
        sec = "; Secure" if secure else ""

        async def send_with_cookie(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                cookie = f"csrf_token={token}; Path=/; SameSite=Lax{sec}"
                headers.append((b"set-cookie", cookie.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_cookie)
