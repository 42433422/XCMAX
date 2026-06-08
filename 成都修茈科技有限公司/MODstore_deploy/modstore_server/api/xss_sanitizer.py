from __future__ import annotations

import json
import re

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

_SCRIPT_RE = re.compile(r"<\s*script[^>]*>.*?<\s*/\s*script\s*>", re.IGNORECASE | re.DOTALL)

# Paths whose bodies must NOT be rewritten: signatures are computed over the
# raw bytes, and any mutation (even stripping <script>) breaks the HMAC/RSA
# verification performed by the downstream handler.
_BYPASS_PATHS: frozenset[str] = frozenset(
    {
        "/api/payment/notify",  # Alipay async notify (RSA signature on raw body)
        "/api/payment/webhook",  # payment webhook delivery
        "/api/webhook",  # generic webhook inbound
        "/api/openapi/proxy",  # OpenAPI connector passthrough
    }
)


def _is_bypass_path(path: str) -> bool:
    for prefix in _BYPASS_PATHS:
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


def _sanitize_value(value):
    if isinstance(value, str):
        # 仅剥离 ``<script>`` 片段；勿对 JSON 字符串做 ``html.escape``，否则会破坏 OpenAPI/YAML 等合法载荷。
        return _SCRIPT_RE.sub("", value)
    if isinstance(value, dict):
        return {k: _sanitize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(v) for v in value]
    return value


def _make_replay_receive(body: bytes, original_receive: Receive) -> Receive:
    _sent = False

    async def receive():
        nonlocal _sent
        if not _sent:
            _sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await original_receive()

    return receive


class XSSSanitizerMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive, send)

        path = request.url.path
        if _is_bypass_path(path):
            await self.app(scope, receive, send)
            return

        if not (path.startswith("/api/") or path.startswith("/v1/") or path.startswith("/admin/")):
            await self.app(scope, receive, send)
            return

        content_type = request.headers.get("content-type", "")

        if "application/json" not in content_type:
            await self.app(scope, receive, send)
            return

        if request.method.upper() not in ("POST", "PUT", "PATCH", "DELETE"):
            await self.app(scope, receive, send)
            return

        body = await request.body()
        if not body:
            await self.app(scope, _make_replay_receive(b"", receive), send)
            return

        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            await self.app(scope, _make_replay_receive(body, receive), send)
            return

        sanitized = _sanitize_value(parsed)
        new_body = json.dumps(sanitized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

        await self.app(scope, _make_replay_receive(new_body, receive), send)
