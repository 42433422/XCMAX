"""Preserve legacy clients while pinning every managed platform credential request."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

import httpx

from modstore_server.platform_model_config import PlatformApiKey


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
                if not stream:
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
            async with client.stream("POST", url, headers=headers, json=body) as response:
                yield response
        else:
            yield await client.post(url, headers=headers, json=body)
