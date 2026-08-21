from __future__ import annotations

import json
from html.parser import HTMLParser

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

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


class _ScriptRemovingParser(HTMLParser):
    """Remove script elements with HTML tokenization, not a bypassable regex."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._script_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() == "script":
            self._script_depth += 1
        elif self._script_depth == 0:
            raw_tag = self.get_starttag_text()
            if raw_tag is not None:
                self._chunks.append(raw_tag)

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag.lower() != "script" and self._script_depth == 0:
            raw_tag = self.get_starttag_text()
            if raw_tag is not None:
                self._chunks.append(raw_tag)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script":
            self._script_depth = max(0, self._script_depth - 1)
        elif self._script_depth == 0:
            self._chunks.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._script_depth == 0:
            self._chunks.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._script_depth == 0:
            self._chunks.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._script_depth == 0:
            self._chunks.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        if self._script_depth == 0:
            self._chunks.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        if self._script_depth == 0:
            self._chunks.append(f"<!{decl}>")

    def handle_pi(self, data: str) -> None:
        if self._script_depth == 0:
            self._chunks.append(f"<?{data}>")

    def unknown_decl(self, data: str) -> None:
        if self._script_depth == 0:
            self._chunks.append(f"<![{data}]>")

    def result(self) -> str:
        return "".join(self._chunks)


def _strip_script_elements(value: str) -> str:
    parser = _ScriptRemovingParser()
    parser.feed(value)
    parser.close()
    return parser.result()


def _sanitize_value(value):
    if isinstance(value, str):
        # 仅剥离 ``<script>`` 片段；勿对 JSON 字符串做 ``html.escape``，否则会破坏 OpenAPI/YAML 等合法载荷。
        return _strip_script_elements(value)
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
