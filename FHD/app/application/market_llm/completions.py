"""Completed chat operations: payload assembly, retry decisions and response ownership."""

from __future__ import annotations

import asyncio
import re

import httpx

from app.application.tool_execution_deadline import (
    check_invocation_deadline,
    remaining_invocation_seconds,
)
from app.infrastructure.modstore_transport import MarketModelError
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .authentication import validate_demo_destination
from .protocols import (
    ChatInput,
    CompletionPorts,
    Connection,
    Payload,
    ResponsePorts,
    Route,
    SyncClientFactory,
)
from .responses import _response_status_code, finish_completion


def post_sync(
    connection: Connection,
    route: Route,
    request: ChatInput,
    allow_failover: bool,
    client_factory: SyncClientFactory,
    response_ports: ResponsePorts,
) -> Payload:
    check_invocation_deadline()
    start = response_ports.clock()
    timeout = remaining_invocation_seconds(connection.timeout)
    with client_factory(
        timeout=httpx.Timeout(timeout, connect=min(10.0, timeout)),
        limits=httpx.Limits(max_keepalive_connections=10, max_connections=30),
        headers=connection.headers(),
    ) as client:
        response = client.post(
            f"{connection.platform_url}/api/llm/chat",
            json=request.payload(
                connection, route, request.messages, allow_failover=allow_failover
            ),
        )
        latency_ms = (response_ports.clock() - start) * 1000.0
        status = _response_status_code(response)
        if status >= 400:
            if request.extra.get("key_source") or request.extra.get("route_token"):
                raise MarketModelError({"status": status})
            raise ValueError(f"平台错误({status}): {response.text[:500]}")
        result = response.json()
    return finish_completion(result, connection, route, latency_ms, response_ports)


def complete_sync(
    connection: Connection, route: Route, request: ChatInput, ports: CompletionPorts
) -> Payload:
    if not connection.platform_url:
        raise ValueError("修茈市场平台URL未配置 (MODSTORE_PLATFORM_URL)")
    validate_demo_destination(connection)
    candidates = ports.candidates(*route)
    last_error: Exception | None = None
    for index, candidate in enumerate(candidates):
        check_invocation_deadline()
        messages = ports.prepare_sync(request.messages, *candidate)
        try:
            return ports.post_sync(
                provider=candidate[0],
                model=candidate[1],
                messages=messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                allow_failover=index == 0,
                extra=request.extra or None,
            )
        except ValueError as exc:
            last_error = exc
            match = re.search(r"平台错误\((\d{3})\)", str(exc))
            status = int(match.group(1)) if match else None
            if index + 1 >= len(candidates) or not ports.failoverable(status, str(exc)):
                raise
            ports.response.logger.warning(
                "[Modstore] 桌面侧换模重试 %s/%s -> %s", *candidate, candidates[index + 1]
            )
    if last_error is not None:
        raise last_error
    raise ValueError("平台聊天失败且无可用备用模型")


async def complete_async(
    connection: Connection, route: Route, request: ChatInput, ports: CompletionPorts
) -> Payload:
    if not connection.platform_url:
        raise ValueError("修茈市场平台URL未配置 (MODSTORE_PLATFORM_URL)")
    candidates = await asyncio.to_thread(ports.candidates, *route)
    last_error: Exception | None = None
    for index, candidate in enumerate(candidates):
        messages = await ports.prepare_async(request.messages, *candidate)
        payload = request.payload(connection, candidate, messages, allow_failover=index == 0)
        start = ports.response.clock()
        try:
            client = await ports.client()
            response = await client.post(
                f"{connection.platform_url}/api/llm/chat",
                json=payload,
                headers=connection.headers(),
            )
            latency_ms = (ports.response.clock() - start) * 1000.0
            status = ports.status_code(response, 200)
            if status >= 400:
                if request.extra.get("key_source") or request.extra.get("route_token"):
                    raise MarketModelError({"status": status})
                error = ValueError(f"平台错误({status}): {response.text[:500]}")
                if index + 1 < len(candidates) and ports.failoverable(status, response.text[:500]):
                    last_error = error
                    continue
                raise error
            return finish_completion(
                response.json(), connection, candidate, latency_ms, ports.response
            )
        except httpx.HTTPError as exc:
            last_error = exc
            if index + 1 < len(candidates) and ports.failoverable(None, str(exc)):
                continue
            raise
        except ValueError:
            raise
        except RECOVERABLE_ERRORS as exc:
            ports.response.logger.error("[Modstore] 调用异常: %s", exc, exc_info=True)
            raise
    if last_error is not None:
        raise last_error
    raise ValueError("平台聊天失败且无可用备用模型")
