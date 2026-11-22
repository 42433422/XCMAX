"""HTTP correlation and full response lifetime, including SSE and disconnects."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.middleware.request_id import ensure_request_id
from app.neuro_bus.tracer import NeuroTracer, SpanStatus
from app.security.log_redaction import redact_log_text
from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _redact_headers(headers: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    skip = {"authorization", "cookie", "set-cookie", "x-api-key", "x-auth-token"}
    try:
        for key, value in headers.items():
            out[str(key)] = (
                "<redacted>" if str(key).lower() in skip else redact_log_text(str(value))[:200]
            )
    except RECOVERABLE_ERRORS:
        pass
    return out


class NeuroHttpTraceMiddleware:
    """ASGI scope stays active until the body finishes; sampling only affects export."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        from opentelemetry import context as otel
        from opentelemetry import trace
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

        headers = Headers(scope=scope)
        extracted = TraceContextTextMapPropagator().extract(dict(headers))
        token = otel.attach(extracted)
        try:
            await self._trace_request(
                scope, receive, send, trace.get_current_span().get_span_context()
            )
        finally:
            otel.detach(token)

    async def _trace_request(self, scope: Scope, receive: Receive, send: Send, parent: Any) -> None:
        request = Request(scope)
        rid = ensure_request_id(request)
        span = NeuroTracer().start_span(
            f"HTTP {request.method}",
            trace_id=f"{parent.trace_id:032x}" if parent.is_valid else None,
            parent_id=f"{parent.span_id:016x}" if parent.is_valid else None,
            tags={"http.request.method": request.method, "request_id": rid},
        )
        started = time.perf_counter_ns()
        base = {
            "request_id": rid,
            "trace_id": span.trace_id,
            "span_id": span.span_id,
            "parent_span_id": span.parent_id,
            "method": request.method,
            "path": request.url.path[:800],
        }
        request.state.trace_id, request.state.span_id = span.trace_id, span.span_id
        enabled = sampled = False
        try:
            from app.neuro_bus.integrations.intent_integration import is_neuro_stack_enabled
            from app.neuro_bus.neuro_trace_config import should_sample_http

            enabled = is_neuro_stack_enabled()
            sampled = enabled and should_sample_http()
        except BOUNDARY_ERRORS:
            logger.debug("neuro http sampling unavailable")

        def publish(event: str, details: dict[str, Any], *, failed: bool = False) -> None:
            if not (sampled or enabled and failed):
                return
            try:
                from app.neuro_bus.application_neuro_bridge import publish_neuro_event

                publish_neuro_event(event, {**base, **details}, domain="global")
            except BOUNDARY_ERRORS:
                logger.debug("neuro http event unavailable")

        status_code = 0
        complete = disconnected = cancelled = False
        error: BaseException | None = None
        error_code = ""
        with span.context(request_id=rid) as context:
            publish(
                "http.request.started",
                {
                    "query": redact_log_text(str(request.url.query))[:500],
                    "client": request.client.host if request.client else "",
                    "headers": _redact_headers(request.headers),
                },
            )

            async def measured_send(message: Message) -> None:
                nonlocal status_code, complete, error_code
                if message["type"] == "http.response.start":
                    status_code = message["status"]
                    response_headers = MutableHeaders(scope=message)
                    response_headers["X-Trace-ID"] = span.trace_id
                    response_headers["X-Request-ID"] = rid
                    if context.traceparent:
                        response_headers["traceparent"] = context.traceparent
                    error_code = response_headers.get("x-error-code", "")[:100]
                await send(message)
                if message["type"] == "http.response.body" and not message.get("more_body", False):
                    complete = True

            async def measured_receive() -> Message:
                nonlocal disconnected
                message = await receive()
                if message["type"] == "http.disconnect":
                    disconnected = True
                return message

            try:
                await self.app(scope, measured_receive, measured_send)
            except asyncio.CancelledError:
                cancelled = True
                raise
            except BOUNDARY_ERRORS as exc:
                error = exc
                raise
            finally:
                cancelled = cancelled or disconnected and not complete
                failed = error is not None or not complete and not cancelled or status_code >= 500
                status = (
                    SpanStatus.ERROR
                    if failed
                    else SpanStatus.CANCELLED
                    if cancelled
                    else SpanStatus.OK
                )
                span.set_tag("http.response.status_code", status_code)
                if error is not None:
                    span.set_tag("error.type", type(error).__name__)
                span.finish(status)
                duration = round(max(0, time.perf_counter_ns() - started) / 1_000_000, 3)
                details = {
                    "status_code": status_code,
                    "duration_ms": duration,
                    "latency_ms": duration,
                    "outcome": status.value,
                }
                if error is not None:
                    details.update(
                        error=redact_log_text(str(error))[:300], error_type=type(error).__name__
                    )
                if error_code:
                    details["error_code"] = error_code
                publish(
                    "http.request.failed"
                    if failed
                    else "http.request.cancelled"
                    if cancelled
                    else "http.request.completed",
                    details,
                    failed=failed,
                )
