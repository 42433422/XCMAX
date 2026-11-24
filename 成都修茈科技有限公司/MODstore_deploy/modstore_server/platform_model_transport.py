"""Preserve legacy clients while pinning every managed platform credential request."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from httpx import AsyncByteStream

from modstore_server import llm_gateway_contract as stream_contract
from modstore_server.platform_model_config import PlatformApiKey

MAX_MODEL_STREAM_BYTES = stream_contract.MAX_STREAM_BYTES


class _ModelStreamBytes:
    def __init__(self, source: Any):
        self.source = source
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        size = 0
        async for chunk in self.source:
            size += len(chunk)
            if size > MAX_MODEL_STREAM_BYTES:
                raise stream_contract.StreamLimitError("model stream wire byte limit exceeded")
            yield chunk

    async def aclose(self) -> None:
        if not self.closed:
            self.closed = True
            await self.source.aclose()


class _HttpxModelStream(_ModelStreamBytes, AsyncByteStream):
    pass


async def bound_model_response(response: Any) -> None:
    """Bound raw SSE bytes before either pinned HTTP client's parser buffers a line.

    Request identity encoding and reject a nonconforming compressed response
    before decoding; checking after HTTPX decompression cannot bound expansion.
    HTTPX owns response cleanup when a response hook raises.
    """
    if response.headers.get("content-encoding", "").strip().lower() not in {"", "identity"}:
        raise stream_contract.StreamLimitError("model stream content encoding is not identity")
    if response.is_stream_consumed:
        if len(response.content) > MAX_MODEL_STREAM_BYTES:
            raise stream_contract.StreamLimitError("model stream wire byte limit exceeded")
        return
    if isinstance(response.stream, _ModelStreamBytes):
        return
    stream_type: type[_ModelStreamBytes] = _HttpxModelStream
    if not isinstance(response, httpx.Response):
        # OpenAI's pinned SDK uses HTTPX2. Both public stream interfaces retain
        # the same ownership contract; no SDK parser or private decoder changes.
        from httpx2 import AsyncByteStream as SDKAsyncByteStream

        class _SDKModelStream(_ModelStreamBytes, SDKAsyncByteStream):
            pass

        stream_type = _SDKModelStream
    response.stream = stream_type(response.stream)


def bound_model_stream_client(client: Any) -> Any:
    """Keep the caller's transport and hooks while applying the stream boundary."""
    client.headers["Accept-Encoding"] = "identity"
    hooks = client.event_hooks["response"]
    if bound_model_response not in hooks:
        hooks.insert(0, bound_model_response)
    return client


def redact_key(value: Any, api_key: str) -> Any:
    if isinstance(value, str):
        return value.replace(api_key, "[REDACTED]") if api_key else value
    if isinstance(value, dict):
        return {redact_key(key, api_key): redact_key(item, api_key) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_key(item, api_key) for item in value]
    return value


@asynccontextmanager
async def llm_http_response(
    url: str,
    api_key: str,
    headers: dict[str, str],
    body: dict[str, Any],
    *,
    timeout: Any,
    limits: Any,
    stream: bool = False,
    method: str = "POST",
):
    if method not in {"GET", "POST"}:
        raise ValueError("unsupported provider request method")
    if stream:
        headers = {**headers, "Accept-Encoding": "identity"}
    managed = isinstance(api_key, PlatformApiKey) and api_key.managed
    options: dict[str, Any] = {"follow_redirects": False, "trust_env": False} if managed else {}
    async with httpx.AsyncClient(timeout=timeout, limits=limits, **options) as client:
        if managed:
            from modstore_server.openapi_connector_runtime import (
                OutboundBlocked,
                pin_url_outbound_safe,
            )

            try:
                target = await asyncio.to_thread(pin_url_outbound_safe, url)
            except (OutboundBlocked, OSError, ValueError):
                raise httpx.RequestError("平台模型地址无法安全连接") from None
            request_body: dict[str, Any] = {"json": body} if method != "GET" else {}
            request = client.build_request(
                method,
                target.request_url,
                headers={**headers, "Host": target.host_header},
                **request_body,
            )
            request.extensions["sni_hostname"] = target.server_hostname
            response = await client.send(request, stream=True)
            upstream = response
            try:
                if stream:
                    await bound_model_response(response)
                else:
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > 8 * 1024 * 1024:
                            raise httpx.RequestError("平台模型响应超过允许大小")
                    response = httpx.Response(
                        response.status_code,
                        content=bytes(content),
                        headers={
                            name: value
                            for name, value in response.headers.items()
                            if name.lower() not in {"content-encoding", "content-length"}
                        },
                        request=request,
                    )
                yield response
            finally:
                await upstream.aclose()
        elif stream:
            request_body = {"json": body} if method != "GET" else {}
            async with client.stream(method, url, headers=headers, **request_body) as response:
                await bound_model_response(response)
                yield response
        elif method == "GET":
            yield await client.get(url, headers=headers)
        else:
            yield await client.post(url, headers=headers, json=body)
