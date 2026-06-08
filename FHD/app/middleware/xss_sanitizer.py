import html
import json
import re

from starlette.types import ASGIApp, Receive, Scope, Send

_SCRIPT_RE = re.compile(r"<\s*script[^>]*>.*?<\s*/\s*script\s*>", re.IGNORECASE | re.DOTALL)


def _sanitize_value(value):
    if isinstance(value, str):
        value = _SCRIPT_RE.sub("", value)
        return html.escape(value)
    if isinstance(value, dict):
        return {k: _sanitize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    return value


class XSSSanitizerMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        if method in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return

        headers_dict = {}
        for key, value in scope.get("headers", []):
            headers_dict[key.decode("latin-1").lower()] = value.decode("latin-1")

        content_type = headers_dict.get("content-type", "")
        if "json" not in content_type:
            await self.app(scope, receive, send)
            return

        body_parts = []
        body_size = 0

        async def receive_body():
            nonlocal body_size
            while True:
                message = await receive()
                if message["type"] == "http.request":
                    body = message.get("body", b"")
                    body_parts.append(body)
                    body_size += len(body)
                    if not message.get("more_body", False):
                        break
                elif message["type"] == "http.disconnect":
                    return message
            return {"type": "http.request", "body": b"".join(body_parts)}

        message = await receive_body()
        if message.get("type") == "http.disconnect":
            await self.app(scope, receive, send)
            return

        raw_body = message.get("body", b"")

        body_to_replay = raw_body
        try:
            if raw_body:
                data = json.loads(raw_body)
                sanitized = _sanitize_value(data)
                body_to_replay = json.dumps(sanitized).encode("utf-8")
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

        body_sent = False

        async def replay_receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": body_to_replay, "more_body": False}
            return await receive()

        await self.app(scope, replay_receive, send)
