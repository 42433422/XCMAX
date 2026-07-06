"""选择性 GZip 压缩中间件（v10 线内迭代 · 性能加固）。

Starlette 自带的 ``GZipMiddleware`` 会对流式响应逐块压缩，SSE 事件可能滞留在
压缩器缓冲区导致对话流卡顿/断流（AI chat stream、员工 SSE 均受影响），因此
本项目此前完全未启用响应压缩，大 JSON 列表接口（订单/产品/会话列表）在
LAN/WAN 上白白多传数倍字节。

本中间件采取保守而安全的策略：

- 仅压缩**单块完整响应**（首个 body 消息 ``more_body=False``）；
  任何流式响应（SSE、分块下载）原样透传，绝不引入缓冲。
- 仅压缩可压缩的 ``Content-Type``（json/text/js/css/svg/xml）。
- 跳过已带 ``Content-Encoding`` 的响应与小于 ``minimum_size`` 的响应。
- 始终补 ``Vary: Accept-Encoding``，保证代理/CDN 缓存正确分片。
"""

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

_DEFAULT_MINIMUM_SIZE = 1024


class ConditionalGZipMiddleware:
    """只压缩非流式、可压缩类型的完整响应；SSE 与流式下载永不受影响。"""

    def __init__(
        self,
        app: ASGIApp,
        minimum_size: int = _DEFAULT_MINIMUM_SIZE,
        compresslevel: int = 6,
    ) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        accept_encoding = Headers(scope=scope).get("accept-encoding", "")
        if "gzip" not in accept_encoding.lower():
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

    def _response_compressible(self, message: Message) -> bool:
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
            # 暂存 start，等首个 body 判断是否流式后再决定压缩与否。
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
        more_body = message.get("more_body", False)

        if (
            more_body
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
