"""OpenTelemetry GenAI 语义约定：工具执行 span 埋点。

只提供最小埋点能力：SDK 未初始化时 ``get_tracer`` 返回 NoOpTracer，
埋点自身失败一律降级为 no-op，不影响工具调用与业务异常语义。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry.trace import Span, Status, StatusCode, get_current_span, set_span_in_context
from opentelemetry.trace import get_tracer as _otel_get_tracer

from app.neuro_bus.tracer import TraceContext, get_trace_context
from app.security.log_redaction import redact_log_text
from app.utils.operational_errors import BOUNDARY_ERRORS


def get_tracer() -> Any:
    """返回本模块 tracer；未配置 TracerProvider 时即 NoOpTracer。"""
    return _otel_get_tracer(__name__)


def _set_attribute(span: Span, key: str, value: Any) -> None:
    """写入属性，失败时仅降级为 no-op。"""
    try:
        span.set_attribute(key, value)
    except BOUNDARY_ERRORS:
        pass


def record_tool_result(span: Span | None, output: dict[str, Any]) -> None:
    """Only an inspected business receipt can mark a tool attempt successful."""
    if span is None:
        return
    success = output.get("success") is True
    _set_attribute(span, "gen_ai.tool.call.result", "success" if success else "error")
    if success:
        return
    code = redact_log_text(str(output.get("error_code") or "tool_failed"))[:128]
    _set_attribute(span, "error.type", redact_log_text(str(output.get("error_type") or code))[:128])
    _set_attribute(span, "error.code", code)
    try:
        span.set_status(Status(StatusCode.ERROR))
    except BOUNDARY_ERRORS:
        pass


def record_tool_exception(span: Span | None, exc: BaseException) -> None:
    """Keep the exception class, without exporting its message or stack secrets."""
    if span is None:
        return
    record_tool_result(
        span,
        {
            "success": False,
            "error_code": "tool_cancelled"
            if isinstance(exc, asyncio.CancelledError)
            else "tool_exception",
            "error_type": type(exc).__name__,
        },
    )
    try:
        span.add_event("exception", {"exception.type": type(exc).__name__})
    except BOUNDARY_ERRORS:
        pass


@contextmanager
def tool_call_span(
    *,
    tool_id: str,
    action: str,
    node_id: str,
    run_id: str | None = None,
    call_id: str | None = None,
    attempt: int = 1,
    trace_id: str | None = None,
    parent_span_id: str | None = None,
    trace_flags: str | int | None = None,
    trace_state: str | None = None,
) -> Iterator[Span | None]:
    """Activate one attempt; callers mark the inspected result before exiting."""
    attributes: dict[str, Any] = {
        "gen_ai.operation.name": "execute_tool",
        "gen_ai.tool.name": str(tool_id),
        "gen_ai.tool.call.id": str(call_id or node_id),
        "xcagi.node_id": str(node_id),
        "xcagi.attempt": attempt,
    }
    if run_id:
        attributes["gen_ai.agent.id"] = str(run_id)
    active = get_trace_context()
    parent_trace = trace_id or active.get("trace_id")
    parent_id = parent_span_id or active.get("span_id")
    parent = (
        TraceContext(parent_trace, parent_id, trace_flags=trace_flags, trace_state=trace_state)
        if parent_trace
        else nullcontext()
    )
    with parent:
        span: Span | None = None
        trace, child_id = parent_trace, None
        inherited = get_trace_context()
        child_flags, child_state = inherited.get("trace_flags"), inherited.get("trace_state")
        try:
            tracer = get_tracer()
            if tracer is not None:
                span = tracer.start_span(f"execute_tool {tool_id}.{action}", attributes=attributes)
                context = span.get_span_context()
                if context.is_valid and format(context.span_id, "016x") != parent_id:
                    trace, child_id = (
                        format(context.trace_id, "032x"),
                        format(context.span_id, "016x"),
                    )
                    child_flags, child_state = (
                        format(context.trace_flags, "02x"),
                        context.trace_state.to_header(),
                    )
        except BOUNDARY_ERRORS:
            span = None
        with TraceContext(trace, child_id, trace_flags=child_flags, trace_state=child_state):
            # API-only/unsampled operation still propagates a distinct attempt id.
            token = None
            try:
                if span is not None:
                    if child_id is None:
                        span = get_current_span()
                    token = otel_context.attach(set_span_in_context(span))
            except BOUNDARY_ERRORS:
                pass
            started = time.perf_counter()
            try:
                yield span
            except BOUNDARY_ERRORS + (asyncio.CancelledError,) as exc:
                record_tool_exception(span, exc)
                raise
            finally:
                if token is not None:
                    try:
                        otel_context.detach(token)
                    except BOUNDARY_ERRORS:
                        pass
                if span is not None:
                    _set_attribute(
                        span, "xcagi.duration_ms", max(0.0, (time.perf_counter() - started) * 1000)
                    )
                    try:
                        span.end()
                    except BOUNDARY_ERRORS:
                        pass
