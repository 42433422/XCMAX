"""Own streaming responses until consumption, cancellation or explicit generator closure."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Iterator
from dataclasses import replace
from itertools import chain

import httpx

from app.application.tool_execution_deadline import (
    check_invocation_deadline,
    remaining_invocation_seconds,
)
from app.infrastructure.chat_stream_lifetime import check_stream_active, owned_model_read

from .completions import (
    _allows_failover,
    _buffer_audited_async_body,
    _buffer_audited_sync_body,
    _can_failover,
    _capture_reviewed_response,
    _failover_extra,
    _status_error,
)


class _Replay:
    def __init__(self, lines):
        self._lines = lines

    def iter_lines(self):
        return iter(self._lines)

    def aiter_lines(self):
        return self._lines


def _completion_payloads(response, sse_payloads):
    """Buffer JSON documents only; SSE status and content must arrive immediately."""
    lines = iter(response.iter_lines())
    first = next((line for line in lines if line.strip()), "")
    if first.lstrip().startswith("{"):
        yield "\n".join(chain([first], lines))
    else:
        yield from sse_payloads(_Replay(chain([first], lines)))


async def _acompletion_payloads(response, sse_payloads):
    lines = response.aiter_lines()
    first = ""
    async for line in lines:
        if line.strip():
            first = line
            break
    if first.lstrip().startswith("{"):
        yield "\n".join([first, *[line async for line in lines]])
        return

    async def remaining():
        yield first
        async for line in lines:
            yield line

    async for data in sse_payloads(_Replay(remaining())):
        yield data


from .protocols import ChatInput, Connection, Route, StreamPorts


def stream_sync(
    connection: Connection, route: Route, request: ChatInput, ports: StreamPorts
) -> Iterator[str]:
    if not connection.platform_url:
        raise ValueError("修茈市场平台URL未配置")
    allow_failover = _allows_failover(request)
    candidates = ports.candidates(*route) if allow_failover else [route]
    last_error: Exception | None = None
    for index, candidate in enumerate(candidates):
        check_stream_active()
        check_invocation_deadline()
        messages = (
            request.messages
            if request.native_vision
            else ports.prepare_sync(request.messages, *candidate)
        )
        attempt = replace(request, extra=_failover_extra(request.extra, index=index))
        payload = attempt.payload(
            connection,
            candidate,
            messages,
            stream=True,
            allow_failover=allow_failover and index == 0,
        )
        timeout = remaining_invocation_seconds(connection.timeout)
        with ports.sync_client(
            timeout=httpx.Timeout(timeout, connect=min(timeout, ports.connect_timeout())),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=30),
            headers=connection.headers(),
        ) as client:
            emitted = False
            try:
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
                        _buffer_audited_sync_body(request, response)
                        for data in _completion_payloads(response, ports.sync_payloads):
                            check_invocation_deadline()
                            emitted = True
                            yield data
                        _capture_reviewed_response(request, connection, response)
                        return
                    response.read()
                    will_failover = index + 1 < len(candidates) and _can_failover(
                        ports, status, response.text[:500]
                    )
                    if not will_failover:
                        _capture_reviewed_response(request, connection, response)
                    error = _status_error(attempt, response, status)
                    if not will_failover:
                        raise error
                    last_error = error
                    ports.logger.warning(
                        "[Modstream] 流式换模 %s/%s -> %s", *candidate, candidates[index + 1]
                    )
            except httpx.HTTPError as exc:
                # 连接/读超时等传输故障：未输出首包时才允许换模。
                if (
                    emitted
                    or index + 1 >= len(candidates)
                    or not _can_failover(ports, None, str(exc))
                ):
                    raise
                last_error = exc
                ports.logger.warning(
                    "[Modstream] 流式传输失败换模 %s/%s -> %s",
                    *candidate,
                    candidates[index + 1],
                )
    if last_error is not None:
        raise last_error
    raise ValueError("平台流式聊天失败且无可用备用模型")


async def stream_async(
    connection: Connection, route: Route, request: ChatInput, ports: StreamPorts
) -> AsyncGenerator[str, None]:
    if not connection.platform_url:
        raise ValueError("修茈市场平台URL未配置")
    allow_failover = _allows_failover(request)
    candidates = await asyncio.to_thread(ports.candidates, *route) if allow_failover else [route]
    last_error: Exception | None = None
    for index, candidate in enumerate(candidates):
        check_stream_active()
        check_invocation_deadline()
        messages = (
            request.messages
            if request.native_vision
            else await ports.prepare_async(request.messages, *candidate)
        )
        attempt = replace(request, extra=_failover_extra(request.extra, index=index))
        payload = attempt.payload(
            connection,
            candidate,
            messages,
            stream=True,
            allow_failover=allow_failover and index == 0,
        )
        client = await ports.async_client()
        emitted = False
        try:
            timeout = remaining_invocation_seconds(connection.timeout)
            async with client.stream(
                "POST",
                f"{connection.platform_url}/api/llm/chat/stream",
                json=payload,
                headers=connection.headers(),
                timeout=httpx.Timeout(timeout, connect=min(timeout, ports.connect_timeout())),
            ) as response:
                status = ports.status_code(response, 200)
                if status >= 400:
                    await response.aread()
                    will_failover = index + 1 < len(candidates) and _can_failover(
                        ports, status, response.text[:500]
                    )
                    if not will_failover:
                        _capture_reviewed_response(request, connection, response)
                    error = _status_error(attempt, response, status)
                    if not will_failover:
                        raise error
                    last_error = error
                    ports.logger.warning(
                        "[Modstream] 流式换模 %s/%s -> %s", *candidate, candidates[index + 1]
                    )
                    continue
                await _buffer_audited_async_body(request, response)
                async for data in _acompletion_payloads(response, ports.async_payloads):
                    check_invocation_deadline()
                    emitted = True
                    yield data
                _capture_reviewed_response(request, connection, response)
                return
        except httpx.HTTPError as exc:
            # 传输故障只在未输出首包时换模，避免重复内容或重复计费。
            if emitted or index + 1 >= len(candidates) or not _can_failover(ports, None, str(exc)):
                raise
            last_error = exc
            ports.logger.warning(
                "[Modstream] 流式传输失败换模 %s/%s -> %s",
                *candidate,
                candidates[index + 1],
            )
    if last_error is not None:
        raise last_error
    raise ValueError("平台流式聊天失败且无可用备用模型")
