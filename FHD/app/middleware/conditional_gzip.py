"""Compress complete text responses without buffering SSE or streamed bodies."""

from __future__ import annotations

import gzip
import io

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_COMPRESSIBLE_TYPES = (
    "application/json",
    "application/javascript",
    "application/xml",
    "application/vnd.api+json",
    "image/svg+xml",
    "text/",
)


class ConditionalGZipMiddleware:
    """Gzip single-message text responses; pass streams through immediately."""

    def __init__(self, app: ASGIApp, minimum_size: int = 1024, compresslevel: int = 6) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        accepted = {
            part.split(";", 1)[0].strip().lower()
            for part in Headers(scope=scope).get("accept-encoding", "").split(",")
        }
        if "gzip" not in accepted:
            await self.app(scope, receive, send)
            return

        responder = _GZipResponder(self.app, self.minimum_size, self.compresslevel)
        await responder(scope, receive, send)


class _GZipResponder:
    def __init__(self, app: ASGIApp, minimum_size: int, compresslevel: int) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel
        self.send: Send | None = None
        self.start_message: Message | None = None
        self.decided = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.send = send
        await self.app(scope, receive, self._send_wrapper)

    @staticmethod
    def _response_compressible(message: Message) -> bool:
        headers = Headers(raw=message.get("headers", []))
        if headers.get("content-encoding"):
            return False
        content_type = (headers.get("content-type") or "").lower()
        if content_type.startswith("text/event-stream"):
            return False
        return any(content_type.startswith(prefix) for prefix in _COMPRESSIBLE_TYPES)

    async def _send_wrapper(self, message: Message) -> None:
        assert self.send is not None
        if message["type"] == "http.response.start":
            self.start_message = message
            return

        if message["type"] != "http.response.body" or self.decided:
            await self.send(message)
            return

        self.decided = True
        start = self.start_message
        self.start_message = None
        if start is None:
            await self.send(message)
            return

        body = message.get("body", b"") or b""
        if (
            message.get("more_body", False)
            or len(body) < self.minimum_size
            or not self._response_compressible(start)
        ):
            self._add_vary_header(start)
            await self.send(start)
            await self.send(message)
            return

        buffer = io.BytesIO()
        with gzip.GzipFile(mode="wb", fileobj=buffer, compresslevel=self.compresslevel, mtime=0) as fh:
            fh.write(body)
        compressed = buffer.getvalue()

        if len(compressed) >= len(body):
            self._add_vary_header(start)
            await self.send(start)
            await self.send(message)
            return

        headers = MutableHeaders(raw=start["headers"])
        headers["Content-Encoding"] = "gzip"
        headers["Content-Length"] = str(len(compressed))
        self._add_vary_header(start)
        await self.send(start)
        await self.send({"type": "http.response.body", "body": compressed, "more_body": False})

    @staticmethod
    def _add_vary_header(start: Message) -> None:
        headers = MutableHeaders(raw=start["headers"])
        vary = headers.get("vary")
        if vary is None:
            headers["Vary"] = "Accept-Encoding"
        elif "accept-encoding" not in vary.lower():
            headers["Vary"] = f"{vary}, Accept-Encoding"
