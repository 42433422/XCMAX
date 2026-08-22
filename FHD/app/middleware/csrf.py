import os
import secrets
from typing import cast

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.utils.operational_errors import RECOVERABLE_ERRORS

_MUTATING_METHODS = {"POST", "PUT", "DELETE", "PATCH"}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _has_verified_bearer(request: Request) -> bool:
    """Only a cryptographically/session verified bearer may replace CSRF protection."""
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        return False
    token = authorization[7:].strip()
    if not token:
        return False
    try:
        from app.security.mobile_jwt import verify_mobile_jwt

        mobile = verify_mobile_jwt(token)
        if mobile and mobile.get("typ") == "access":
            return True
        from app.security.web_jwt import verify_web_jwt

        web = verify_web_jwt(token)
        if web and web.get("typ") == "access":
            return True
        from app.application.facades.session_facade import get_session_service

        return get_session_service().validate_session(token) is not None
    except RECOVERABLE_ERRORS:  # noqa: BLE001 - authentication failure must fail closed
        return False


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


def _csrf_exempt_sync_api(scope: Scope) -> bool:
    """节点同步入口：桌面端 / 企业端后台互推变更，无浏览器 csrf_token。"""
    path = (scope.get("path") or "").rstrip("/")
    return path.endswith("/api/xcmax/sync/receive")


def _csrf_exempt_kellai_pairing(scope: Scope) -> bool:
    """客来来桌面端的本机配对回调没有浏览器 Cookie。

    路由层还会验证回环来源和一次性授权密钥；这里额外要求专用请求头，
    避免普通跨站表单请求绕过 CSRF。
    """
    path = (scope.get("path") or "").rstrip("/")
    if not path.startswith("/api/kellai/binding/"):
        return False
    headers = dict(scope.get("headers") or [])
    return cast("bool", headers.get(b"x-kellai-local-pairing", b"") == b"1")


def _csrf_exempt_ops_autonomy(scope: Scope) -> bool:
    """CI / CVM watcher → approval ledger：机器调用只有 X-Autonomy-Token，无浏览器 CSRF。

    路由层 ``ops_autonomy._auth`` 仍校验 webhook token；此处仅免除双提交 Cookie。
    要求带 ``X-Autonomy-Token`` 或 ``Authorization: Bearer``，避免裸 POST 绕过 CSRF。
    """
    path = (scope.get("path") or "").rstrip("/")
    # Also match nginx path prefix /fhd-api/api/ops/autonomy/...
    if "/api/ops/autonomy" not in path:
        return False
    headers = {k: v for k, v in (scope.get("headers") or [])}
    if (headers.get(b"x-autonomy-token") or b"").strip():
        return True
    auth = (headers.get(b"authorization") or b"").strip().lower()
    return auth.startswith(b"bearer ")


def _csrf_exempt_founder_autonomy_refresh(scope: Scope) -> bool:
    """Allow the unattended scorecard refresh through the browser CSRF gate.

    This is deliberately narrower than a founder-autonomy prefix exemption:
    the route must be the internal refresh endpoint and must present both
    credentials that the route validates independently.  A bearer alone or an
    automation token alone is not sufficient.
    """
    path = (scope.get("path") or "").rstrip("/")
    if not path.endswith("/api/xcmax/ops/founder-autonomy/refresh-internal"):
        return False
    headers = {k: v for k, v in (scope.get("headers") or [])}
    autonomy_token = (headers.get(b"x-autonomy-token") or b"").strip()
    authorization = (headers.get(b"authorization") or b"").strip().lower()
    return bool(autonomy_token) and authorization.startswith(b"bearer ")


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
            if _csrf_exempt_sync_api(scope):
                await self.app(scope, receive, send)
                return
            if _csrf_exempt_kellai_pairing(scope):
                await self.app(scope, receive, send)
                return
            if _csrf_exempt_ops_autonomy(scope):
                await self.app(scope, receive, send)
                return
            if _csrf_exempt_founder_autonomy_refresh(scope):
                await self.app(scope, receive, send)
                return
            path = (scope.get("path") or "").rstrip("/")
            if path.startswith("/api/mobile/v1/pairing/"):
                await self.app(scope, receive, send)
                return
            if path.startswith("/api/mobile/v1/relay/"):
                await self.app(scope, receive, send)
                return
            # 内部服务端调用（带 X-Internal-Api-Key，如 MODstore→FHD 员工 IM 投递）：非浏览器请求，
            # 由端点自身的 API-Key 鉴权保护，免 CSRF 双提交。
            if path.startswith("/api/internal/") and request.headers.get("x-internal-api-key"):
                await self.app(scope, receive, send)
                return

            if _has_verified_bearer(request):
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
