from __future__ import annotations

import secrets

from starlette.types import ASGIApp, Receive, Scope, Send

from modstore_server.api.csp_policy import (
    build_enforced_csp,
    build_report_only_strict_csp,
    build_swagger_csp,
)


def _path_from_scope(scope: Scope) -> str:
    raw = scope.get("path", b"")
    if isinstance(raw, (bytes, bytearray)):
        return raw.decode("utf-8", errors="replace")
    return str(raw or "")


def _is_swagger_like_path(path: str) -> bool:
    return path.startswith("/docs") or path.startswith("/redoc") or path == "/openapi.json"


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path = _path_from_scope(scope)
        use_swagger_csp = _is_swagger_like_path(path)
        nonce = secrets.token_urlsafe(16) if not use_swagger_csp else ""

        async def send_with_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-content-type-options", b"nosniff"))
                headers.append((b"x-frame-options", b"DENY"))
                headers.append((b"referrer-policy", b"strict-origin-when-cross-origin"))
                if use_swagger_csp:
                    csp = build_swagger_csp().encode("utf-8")
                else:
                    csp = build_enforced_csp(nonce).encode("utf-8")
                headers.append((b"content-security-policy", csp))
                if not use_swagger_csp:
                    headers.append(
                        (
                            b"content-security-policy-report-only",
                            build_report_only_strict_csp().encode("utf-8"),
                        )
                    )
                scheme = scope.get("scheme", "http")
                if scheme == "https":
                    headers.append(
                        (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
                    )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
