import os

from starlette.types import ASGIApp, Receive, Scope, Send

from app.security.lan_config import normalize_lan_guard_path


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                path = normalize_lan_guard_path(scope.get("path") or "/")
                qs = dict(
                    pair.split(b"=", 1)
                    for pair in scope.get("query_string", b"").split(b"&")
                    if b"=" in pair
                )
                is_sandbox = qs.get(b"sandbox") in (b"1", b"true")
                is_dashboard_embed = path.startswith("/xcmax-dashboard/")
                is_desktop_mode = os.environ.get("XCAGI_DESKTOP_MODE") == "1"
                if is_sandbox:
                    security_headers = {
                        b"x-content-type-options": b"nosniff",
                        b"referrer-policy": b"strict-origin-when-cross-origin",
                        b"content-security-policy": b"default-src 'self' 'unsafe-inline' 'unsafe-eval'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' ws: wss: http: https:; frame-ancestors *;",
                    }
                elif is_dashboard_embed:
                    security_headers = {
                        b"x-content-type-options": b"nosniff",
                        b"x-frame-options": b"SAMEORIGIN",
                        b"referrer-policy": b"strict-origin-when-cross-origin",
                        b"content-security-policy": b"default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob:; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://fonts.googleapis.cn; img-src 'self' data: blob:; font-src 'self' data: https://fonts.gstatic.com https://fonts.gstatic.cn; connect-src 'self' ws: wss: http: https:; frame-ancestors 'self'",
                    }
                else:
                    security_headers = {
                        b"x-content-type-options": b"nosniff",
                        b"x-frame-options": b"DENY",
                        b"referrer-policy": b"strict-origin-when-cross-origin",
                        b"content-security-policy": (
                            b"default-src 'self'; "
                            + (
                                b"script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                                if is_desktop_mode
                                else b"script-src 'self' 'unsafe-inline'; "
                            )
                            + b"style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                            + b"img-src 'self' data: blob:; "
                            + b"font-src 'self' data: https://fonts.gstatic.com; "
                            + b"connect-src 'self' ws: wss:"
                        ),
                    }
                scheme = scope.get("scheme", "http")
                if scheme == "https":
                    security_headers[b"strict-transport-security"] = (
                        b"max-age=31536000; includeSubDomains"
                    )
                for key, value in security_headers.items():
                    headers[key] = value
                message["headers"] = list(headers.items())
            await send(message)

        await self.app(scope, receive, send_with_headers)
