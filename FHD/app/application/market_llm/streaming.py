"""Own streaming responses until consumption, cancellation or explicit generator closure."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Iterator

import httpx

from app.infrastructure.chat_stream_lifetime import check_stream_active, owned_model_read

from .completions import _audit_allows_failover, _capture_reviewed_response


class _Replay:
    def __init__(self, lines: list[str]):
        self._lines = lines

    def iter_lines(self):
        return iter(self._lines)

    async def aiter_lines(self):
        for line in self._lines:
            yield line


def _json_document(lines: list[str]) -> str | None:
    body = "\n".join(lines).lstrip()
    if body.startswith("{") and not any(
        line.lstrip().startswith(("event:", "data:")) for line in lines
    ):
        return body
    return None


def _completion_payloads(response, sse_payloads):
    """One JSON document stays one payload. Event streams stay line-oriented."""
    lines = [line for line in response.iter_lines()]
    document = _json_document(lines)
    if document is not None:
        yield document
        return
    yield from sse_payloads(_Replay(lines))


async def _acompletion_payloads(response, sse_payloads):
    lines = [line async for line in response.aiter_lines()]
    document = _json_document(lines)
    if document is not None:
        yield document
        return
    async for data in sse_payloads(_Replay(lines)):
        yield data


from .protocols import ChatInput, Connection, Route, StreamPorts
from .responses import market_response_error


def stream_sync(
    connection: Connection, route: Route, request: ChatInput, ports: StreamPorts
) -> Iterator[str]:
    if not connection.platform_url:
        raise ValueError("修茈市场平台URL未配置")
    allow_failover = request.extra.get("allow_failover") is not False
    candidates = ports.candidates(*route) if allow_failover else [route]
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
                        for data in _completion_payloads(response, ports.sync_payloads):
                            emitted = True
                            yield data
                        _capture_reviewed_response(request, connection, response)
                        return
                    response.read()
                    will_failover = (
                        index + 1 < len(candidates)
                        and ports.failoverable(status, response.text[:500])
                        and _audit_allows_failover(request.extra)
                    )
                    if not will_failover:
                        _capture_reviewed_response(request, connection, response)
                    if request.extra.get("key_source") or request.extra.get("route_token"):
                        raise market_response_error(response, status)
                    text = response.text[:500]
                    error = ValueError(f"平台错误({status}): {text}")
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
                    or not ports.failoverable(None, str(exc))
                    or not _audit_allows_failover(request.extra)
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
    allow_failover = request.extra.get("allow_failover") is not False
    candidates = await asyncio.to_thread(ports.candidates, *route) if allow_failover else [route]
    last_error: Exception | None = None
    for index, candidate in enumerate(candidates):
        messages = await ports.prepare_async(request.messages, *candidate)
        payload = request.payload(
            connection, candidate, messages, stream=True, allow_failover=index == 0
        )
        client = await ports.async_client()
        emitted = False
        try:
            async with client.stream(
                "POST",
                f"{connection.platform_url}/api/llm/chat/stream",
                json=payload,
                headers=connection.headers(),
            ) as response:
                status = ports.status_code(response, 200)
                if status >= 400:
                    await response.aread()
                    will_failover = (
                        index + 1 < len(candidates)
                        and ports.failoverable(status, response.text[:500])
                        and _audit_allows_failover(request.extra)
                    )
                    if not will_failover:
                        _capture_reviewed_response(request, connection, response)
                    if request.extra.get("key_source") or request.extra.get("route_token"):
                        raise market_response_error(response, status)
                    text = response.text[:500]
                    error = ValueError(f"平台错误({status}): {text}")
                    if not will_failover:
                        raise error
                    last_error = error
                    ports.logger.warning(
                        "[Modstream] 流式换模 %s/%s -> %s", *candidate, candidates[index + 1]
                    )
                    continue
                async for data in _acompletion_payloads(response, ports.async_payloads):
                    emitted = True
                    yield data
                _capture_reviewed_response(request, connection, response)
                return
        except httpx.HTTPError as exc:
            # 传输故障只在未输出首包时换模，避免重复内容或重复计费。
            if (
                emitted
                or index + 1 >= len(candidates)
                or not ports.failoverable(None, str(exc))
                or not _audit_allows_failover(request.extra)
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
