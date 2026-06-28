import os
import secrets

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

_MUTATING_METHODS = {"POST", "PUT", "DELETE", "PATCH"}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _csrf_exempt_sandbox_modstore_install(scope: Scope) -> bool:
    """MODstore 服务端用 httpx 推送 .xcmod；部分反向代理会剥离 Authorization，导致仅靠 Bearer 仍 403。"""
    if (os.environ.get("XCAGI_SANDBOX_INSTANCE") or "").strip() != "1":
        return False
    path = (scope.get("path") or "").rstrip("/")
    return path.endswith("/api/mod-store/install")


def _csrf_exempt_public_auth(scope: Scope) -> bool:
    """登录/登出时尚无会话，且 SPA 与 API 跨域时浏览器无法把 API 域的 csrf Cookie 读回给 JS 填头。

    仍依赖用户名密码校验；与常见「登录 POST 不做 CSRF 双提交」一致。可用环境变量关闭：
    ``XCAGI_CSRF_EXEMPT_AUTH=0``。
    """
    if (os.environ.get("XCAGI_CSRF_EXEMPT_AUTH") or "1").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return False
    path = (scope.get("path") or "").rstrip("/")
    return (
        path.endswith("/api/auth/login")
        or path.endswith("/api/auth/login-with-phone-code")
        or path.endswith("/api/auth/logout")
        or path.endswith("/api/auth/qr/issue")
        or path.endswith("/api/mobile/v1/auth/login")
        or path.endswith("/api/mobile/v1/auth/login-with-phone-code")
        or path.endswith("/api/mobile/v1/auth/refresh")
        or path.endswith("/api/mobile/v1/auth/oidc/exchange")
        or path.endswith("/api/mobile/v1/auth/qr/confirm")
        or path.endswith("/api/market/send-phone-code")
        or path.endswith("/api/xcmax/admin/login")
        or path.endswith("/api/xcmax/admin/logout")
    )


def _csrf_exempt_aiopen(scope: Scope) -> bool:
    """AIOPEN 对外 MCP/API 面：外部 Agent（Cursor/Claude）无 CSRF Cookie，安全由 X-AIOPEN-Key + LAN 承担。"""
    path = (scope.get("path") or "").rstrip("/")
    return path.startswith("/api/aiopen") or path.startswith("/api/ai/qclaw")


def _csrf_exempt_internal_api(scope: Scope) -> bool:
    """内部跨进程 endpoint：MODstore → FHD HTTP 桥接，无浏览器会话，安全由 X-Internal-Api-Key 承担。"""
    path = (scope.get("path") or "").rstrip("/")
    return path.startswith("/api/internal/")


class CSRFMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)

        if request.method in _SAFE_METHODS:
            csrf_cookie = request.cookies.get("csrf_token")
            if not csrf_cookie:
                new_token = secrets.token_hex(32)

                async def send_with_cookie(message):
                    if message["type"] == "http.response.start":
                        headers = list(message.get("headers", []))
                        headers.append(
                            (
                                b"set-cookie",
                                f"csrf_token={new_token}; Path=/; SameSite=Lax".encode("latin-1"),
                            )
                        )
                        message["headers"] = headers
                    await send(message)

                await self.app(scope, receive, send_with_cookie)
            else:
                await self.app(scope, receive, send)
            return

        if request.method in _MUTATING_METHODS:
            if _csrf_exempt_sandbox_modstore_install(scope):
                await self.app(scope, receive, send)
                return
            if _csrf_exempt_public_auth(scope):
                await self.app(scope, receive, send)
                return
            if _csrf_exempt_aiopen(scope):
                await self.app(scope, receive, send)
                return
            if _csrf_exempt_internal_api(scope):
                await self.app(scope, receive, send)
                return
            path = (scope.get("path") or "").rstrip("/")
            if path.startswith("/api/mobile/v1/pairing/"):
                await self.app(scope, receive, send)
                return
            if path.startswith("/api/mobile/v1/relay/"):
                await self.app(scope, receive, send)
                return

            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                await self.app(scope, receive, send)
                return

            csrf_cookie = request.cookies.get("csrf_token")
            csrf_header = request.headers.get("x-csrf-token")

            if not csrf_cookie or not csrf_header:
                response = JSONResponse(
                    {"success": False, "message": "CSRF token missing"},
                    status_code=403,
                )
                await response(scope, receive, send)
                return

            if not secrets.compare_digest(csrf_cookie, csrf_header):
                response = JSONResponse(
                    {"success": False, "message": "CSRF token mismatch"},
                    status_code=403,
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)
