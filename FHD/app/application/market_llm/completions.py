"""Completed chat operations: payload assembly, retry decisions and response ownership."""

from __future__ import annotations

import asyncio
import re

import httpx

from app.application.elt.errors import provider_http_status
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
from .responses import _response_status_code, finish_completion, market_response_error


def _failover_extra(extra: dict | None, *, primary: bool) -> dict:
    """Drop pinned route credentials once we leave the primary candidate."""
    payload = dict(extra or {})
    if primary:
        return payload
    for key in ("route_token", "key_source", "config_revision"):
        payload.pop(key, None)
    return payload


def _audit_allows_failover(extra: dict | None) -> bool:
    """Audited calls failover only when allow_failover is explicitly True."""
    payload = extra or {}
    if payload.get("_reviewed_excel_audit_response") is None:
        return True
    return payload.get("allow_failover") is True


def _status_error(request: ChatInput, response: httpx.Response, status: int) -> Exception:
    if request.extra.get("key_source") or request.extra.get("route_token"):
        error: Exception = market_response_error(response, status)
    else:
        error = ValueError(f"平台错误({status}): {response.text[:500]}")
    error.response = response  # type: ignore[attr-defined]
    return error


def _capture_reviewed_response(
    request: ChatInput, connection: Connection, response: httpx.Response
):
    callback = request.extra.get("_reviewed_excel_audit_response")
    if callback is not None:
        raw = response.content
        if any(
            isinstance(token, str) and token and token.encode() in raw
            for token in (connection.auth_token, request.extra.get("route_token"))
        ):
            raise ValueError("模型响应包含敏感凭据，未归档")
        callback(raw, response.status_code, response.headers.get("x-request-id"))


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
            # Audited single-shot captures here before the error body is parsed.
            # Explicit allow_failover=True defers capture to complete_* terminal attempt.
            if (
                request.extra.get("_reviewed_excel_audit_response") is not None
                and request.extra.get("allow_failover") is not True
            ):
                _capture_reviewed_response(request, connection, response)
            raise _status_error(request, response, status)
        _capture_reviewed_response(request, connection, response)
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
                extra=_failover_extra(request.extra, primary=index == 0) or None,
            )
        except (MarketModelError, ValueError) as exc:
            last_error = exc
            status = provider_http_status(exc)
            if status is None:
                match = re.search(r"平台错误\((\d{3})\)", str(exc))
                status = int(match.group(1)) if match else None
            can_failover = (
                index + 1 < len(candidates)
                and ports.failoverable(status, str(exc))
                and _audit_allows_failover(request.extra)
            )
            if can_failover:
                ports.response.logger.warning(
                    "[Modstore] 桌面侧换模重试 %s/%s -> %s", *candidate, candidates[index + 1]
                )
                continue
            # Terminal failure: archive once when post_sync deferred capture.
            response = getattr(exc, "response", None)
            if response is not None and _audit_allows_failover(request.extra):
                _capture_reviewed_response(request, connection, response)
            raise
    if last_error is not None:
        raise last_error
    raise ValueError("平台聊天失败且无可用备用模型")


async def complete_async(
    connection: Connection, route: Route, request: ChatInput, ports: CompletionPorts
) -> Payload:
    if not connection.platform_url:
        raise ValueError("修茈市场平台URL未配置 (MODSTORE_PLATFORM_URL)")
    allow_failover = request.extra.get("allow_failover") is not False
    candidates = await asyncio.to_thread(ports.candidates, *route) if allow_failover else [route]
    last_error: Exception | None = None
    for index, candidate in enumerate(candidates):
        messages = await ports.prepare_async(request.messages, *candidate)
        attempt = ChatInput(
            messages,
            request.temperature,
            request.max_tokens,
            _failover_extra(request.extra, primary=index == 0),
        )
        payload = attempt.payload(
            connection, candidate, messages, allow_failover=allow_failover and index == 0
        )
        start = ports.response.clock()
        try:
            client = await ports.client()
            response = await client.post(
                f"{connection.platform_url}/api/llm/chat",
                json=payload,
                headers=connection.headers(),
            )
        except httpx.HTTPError as exc:
            last_error = exc
            if (
                index + 1 < len(candidates)
                and ports.failoverable(None, str(exc))
                and _audit_allows_failover(request.extra)
            ):
                continue
            raise
        except ValueError:
            raise
        except RECOVERABLE_ERRORS as exc:
            ports.response.logger.error("[Modstore] 调用异常: %s", exc, exc_info=True)
            raise
        latency_ms = (ports.response.clock() - start) * 1000.0
        status = ports.status_code(response, 200)
        if status >= 400:
            will_failover = (
                index + 1 < len(candidates)
                and ports.failoverable(status, response.text[:500])
                and _audit_allows_failover(request.extra)
            )
            # Archive before parsing the error body so audited receipts stay exact.
            if not will_failover:
                _capture_reviewed_response(request, connection, response)
            error = _status_error(attempt, response, status)
            if will_failover:
                last_error = error
                ports.response.logger.warning(
                    "[Modstore] 桌面侧换模重试 %s/%s -> %s",
                    *candidate,
                    candidates[index + 1],
                )
                continue
            raise error
        _capture_reviewed_response(request, connection, response)
        return finish_completion(response.json(), connection, candidate, latency_ms, ports.response)
    if last_error is not None:
        raise last_error
    raise ValueError("平台聊天失败且无可用备用模型")
