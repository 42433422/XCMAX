"""Own streaming responses until consumption, cancellation or explicit generator closure."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator

import httpx

from app.infrastructure.chat_stream_lifetime import check_stream_active, owned_model_read
from app.infrastructure.modstore_transport import MarketModelError

from .protocols import ChatInput, Connection, Route, StreamPorts


def stream_sync(
    connection: Connection, route: Route, request: ChatInput, ports: StreamPorts
) -> Iterator[str]:
    if not connection.platform_url:
        raise ValueError("修茈市场平台URL未配置")
    candidates = ports.candidates(*route)
    last_error: Exception | None = None
    for index, candidate in enumerate(candidates):
        check_stream_active()
        messages = ports.prepare_sync(request.messages, *candidate)
        payload = request.payload(
            connection, candidate, messages, stream=True, allow_failover=index == 0
        )
        with ports.sync_client(
            timeout=httpx.Timeout(connection.timeout, connect=ports.connect_timeout()),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=30),
            headers=connection.headers(),
        ) as client:
            with (
                client.stream(
                    "POST", f"{connection.platform_url}/api/llm/chat/stream", json=payload
                ) as response,
                owned_model_read(response),
            ):
                check_stream_active()
                status = ports.status_code(response, 200)
                if status < 400:
                    # No retry after output has begun: replaying a partial answer
                    # could duplicate visible output or an upstream billed call.
                    yield from ports.sync_payloads(response)
                    return
                if request.extra.get("key_source") or request.extra.get("route_token"):
                    raise MarketModelError({"status": status})
                text = response.read().decode("utf-8", errors="ignore")[:500]
                error = ValueError(f"平台错误({status}): {text}")
                if index + 1 >= len(candidates) or not ports.failoverable(status, text):
                    raise error
                last_error = error
                ports.logger.warning(
                    "[Modstream] 流式换模 %s/%s -> %s", *candidate, candidates[index + 1]
                )
    if last_error is not None:
        raise last_error
    raise ValueError("平台流式聊天失败且无可用备用模型")


async def stream_async(
    connection: Connection, route: Route, request: ChatInput, ports: StreamPorts
) -> AsyncGenerator[str, None]:
    if not connection.platform_url:
        raise ValueError("修茈市场平台URL未配置")
    messages = await ports.prepare_async(request.messages, *route)
    payload = request.payload(connection, route, messages, stream=True)
    client = await ports.async_client()
    async with client.stream(
        "POST",
        f"{connection.platform_url}/api/llm/chat/stream",
        json=payload,
        headers=connection.headers(),
    ) as response:
        status = ports.status_code(response, 200)
        if status >= 400 and (request.extra.get("key_source") or request.extra.get("route_token")):
            raise MarketModelError({"status": status})
        response.raise_for_status()
        async for data in ports.async_payloads(response):
            yield data
