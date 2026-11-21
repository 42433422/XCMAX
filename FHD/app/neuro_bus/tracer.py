"""
链路追踪器（Tracer）

提供跨领域的链路追踪，类似 OpenTelemetry 的 span 模型
支持分布式追踪和性能分析
"""

import asyncio
import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any

from app.neuro_bus.events.events_base import NeuroEvent
from app.utils.operational_errors import BOUNDARY_ERRORS

logger = logging.getLogger(__name__)


class SpanStatus(Enum):
    """Span 状态"""

    OK = "ok"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class Span:
    """
    追踪 Span

    表示一个操作单元，包含时间、标签和事件
    内部委托 OTel SDK（可用时）
    """

    span_id: str
    trace_id: str
    parent_id: str | None
    name: str
    start_time: float
    end_time: float | None = None
    status: SpanStatus = SpanStatus.OK
    tags: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    _started_ns: int = field(default_factory=time.perf_counter_ns, init=False, repr=False)
    _duration_ms: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self):
        if not self.span_id:
            self.span_id = uuid.uuid4().hex[:16]
        self._otel_span = None
        try:
            from opentelemetry import trace
            from opentelemetry.context import Context

            parent = otel_context(self.trace_id, self.parent_id) or Context()
            self._otel_span = trace.get_tracer("xcagi.neurobus").start_span(
                self.name, context=parent, attributes=self.tags
            )
            context = self._otel_span.get_span_context()
            # A NoOpTracer can return the parent unchanged; it is not a new span.
            if (
                isinstance(context.trace_id, int)
                and context.trace_id > 0
                and isinstance(context.span_id, int)
                and context.span_id > 0
                and f"{context.span_id:016x}" != self.parent_id
            ):
                if len(self.trace_id) == 32:
                    self.trace_id = f"{context.trace_id:032x}"
                if len(self.span_id) == 16:
                    self.span_id = f"{context.span_id:016x}"
        except BOUNDARY_ERRORS:
            logger.debug("OTel span creation unavailable")

    def _export(self, method: str, *args) -> None:
        if self._otel_span is not None:
            try:
                getattr(self._otel_span, method)(*args)
            except BOUNDARY_ERRORS:
                logger.debug("OTel span operation unavailable: %s", method)

    @contextmanager
    def context(self, request_id: str | None = None):
        """Activate the SDK span itself so its sampling decision is preserved."""
        token = None
        try:
            from opentelemetry import context as otel
            from opentelemetry import trace

            native = self._otel_span.get_span_context() if self._otel_span is not None else None
            if (
                native is not None
                and native.is_valid
                and f"{native.trace_id:032x}" == self.trace_id
                and f"{native.span_id:016x}" == self.span_id
            ):
                token = otel.attach(trace.set_span_in_context(self._otel_span))
        except BOUNDARY_ERRORS:
            pass
        try:
            with TraceContext(self.trace_id, self.span_id, request_id=request_id) as context:
                yield context
        finally:
            if token is not None:
                try:
                    otel.detach(token)
                except BOUNDARY_ERRORS:
                    pass

    def finish(self, status: SpanStatus = SpanStatus.OK):
        """完成一次；耗时不受系统时间回拨影响。"""
        if self.end_time is not None:
            return
        self._duration_ms = max(0, time.perf_counter_ns() - self._started_ns) / 1_000_000
        self.end_time = time.time()
        self.status = status
        if self._otel_span is not None:
            try:
                from opentelemetry.trace import Status, StatusCode

                if status == SpanStatus.ERROR:
                    self._export("set_status", Status(StatusCode.ERROR))
                elif status == SpanStatus.CANCELLED:
                    self._export("set_attribute", "xcagi.cancelled", True)
            except ImportError:
                pass
            self._export("end")

    def add_event(self, name: str, attributes: dict[str, Any] | None = None):
        """添加事件"""
        self.events.append(
            {
                "name": name,
                "timestamp": time.time(),
                "attributes": attributes or {},
            }
        )
        self._export("add_event", name, attributes or {})

    def set_tag(self, key: str, value: Any):
        """设置标签"""
        self.tags[key] = value
        self._export("set_attribute", key, value)

    @property
    def duration_ms(self) -> float | None:
        """获取持续时间（毫秒）"""
        if self._duration_ms is not None:
            return self._duration_ms
        # Compatibility for persisted spans constructed with explicit timestamps.
        if self.end_time is not None:
            return max(0, self.end_time - self.start_time) * 1000
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_id": self.parent_id,
            "parent_span_id": self.parent_id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "status": self.status.value,
            "tags": self.tags,
            "events": self.events,
        }


# Business and OTel contexts are scoped explicitly; creating a span never leaks one.
current_trace: ContextVar[str | None] = ContextVar("current_trace", default=None)
current_span: ContextVar[str | None] = ContextVar("current_span", default=None)
current_request_id: ContextVar[str | None] = ContextVar("current_request_id", default=None)


def otel_context(
    trace_id: str | None,
    span_id: str | None,
    *,
    trace_flags: int | str | None = None,
    trace_state: str | None = None,
):
    """Validate using the W3C propagator; preserve active sampling/tracestate."""
    if not trace_id or not span_id:
        return None
    try:
        from opentelemetry import trace
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

        active = trace.get_current_span().get_span_context()
        same_trace = active.is_valid and f"{active.trace_id:032x}" == trace_id
        flags = trace_flags
        if flags is None:
            flags = active.trace_flags if same_trace else 1
        flags = int(flags, 16) if isinstance(flags, str) else int(flags)
        carrier = {"traceparent": f"00-{trace_id}-{span_id}-{flags:02x}"}
        if trace_state is not None:
            carrier["tracestate"] = trace_state
        elif same_trace:
            carrier["tracestate"] = active.trace_state.to_header()
        context = TraceContextTextMapPropagator().extract(carrier)
        return context if trace.get_current_span(context).get_span_context().is_valid else None
    except BOUNDARY_ERRORS:
        return None


def get_trace_context() -> dict[str, str]:
    """Read correlation IDs without creating a new trace or exposing request data."""
    values = {
        "trace_id": current_trace.get(),
        "span_id": current_span.get(),
        "request_id": current_request_id.get(),
    }
    try:
        from opentelemetry import trace

        context = trace.get_current_span().get_span_context()
        if context.is_valid:
            values.update(
                trace_id=f"{context.trace_id:032x}",
                span_id=f"{context.span_id:016x}",
                trace_flags=f"{int(context.trace_flags):02x}",
                trace_state=context.trace_state.to_header(),
            )
    except BOUNDARY_ERRORS:
        pass
    return {key: value for key, value in values.items() if value}


class TraceContext:
    """Restore both business and OTel context, including background task resumes."""

    def __init__(
        self,
        trace_id: str | None = None,
        span_id: str | None = None,
        request_id: str | None = None,
        *,
        trace_flags: int | str | None = None,
        trace_state: str | None = None,
    ):
        self.trace_id = trace_id or uuid.uuid4().hex
        self.span_id = span_id or uuid.uuid4().hex[:16]
        self.request_id = request_id
        self.trace_flags, self.trace_state = trace_flags, trace_state
        self._tokens: list[tuple[ContextVar[str | None], Token[str | None]]] = []
        self._otel_token = None

    def __enter__(self):
        self._tokens = [
            (current_trace, current_trace.set(self.trace_id)),
            (current_span, current_span.set(self.span_id)),
        ]
        if self.request_id is not None:
            self._tokens.append((current_request_id, current_request_id.set(self.request_id)))
        context = otel_context(
            self.trace_id, self.span_id, trace_flags=self.trace_flags, trace_state=self.trace_state
        )
        if context is not None:
            try:
                from opentelemetry import context as otel
                from opentelemetry import trace

                active = trace.get_current_span().get_span_context()
                restored = trace.get_current_span(context).get_span_context()
                if not (
                    active.is_valid
                    and f"{active.trace_id:032x}" == self.trace_id
                    and f"{active.span_id:016x}" == self.span_id
                    and active.trace_flags == restored.trace_flags
                    and active.trace_state == restored.trace_state
                ):
                    self._otel_token = otel.attach(context)
            except BOUNDARY_ERRORS:
                logger.debug("OTel context attachment unavailable")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._otel_token is not None:
            try:
                from opentelemetry import context as otel

                otel.detach(self._otel_token)
            except BOUNDARY_ERRORS:
                logger.debug("OTel context detachment unavailable")
            self._otel_token = None
        for variable, token in reversed(self._tokens):
            variable.reset(token)
        self._tokens = []

    @property
    def traceparent(self) -> str | None:
        context = otel_context(
            self.trace_id, self.span_id, trace_flags=self.trace_flags, trace_state=self.trace_state
        )
        if context is None:
            return None
        try:
            from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

            carrier: dict[str, str] = {}
            TraceContextTextMapPropagator().inject(carrier, context=context)
            return carrier.get("traceparent")
        except BOUNDARY_ERRORS:
            return None


class NeuroTracer:
    """
    神经链路追踪器

    提供：
    - 自动 span 创建
    - 跨领域追踪传播
    - 性能分析数据
    """

    def __init__(self, max_spans: int = 10000):
        self._spans: dict[str, Span] = {}
        self._trace_roots: dict[str, str] = {}  # trace_id -> root_span_id
        self._max_spans = max_spans

    def start_span(
        self,
        name: str,
        trace_id: str | None = None,
        parent_id: str | None = None,
        tags: dict[str, Any] | None = None,
    ) -> Span:
        """
        开始一个新的 Span
        """
        context = get_trace_context()
        trace_id = trace_id or context.get("trace_id") or uuid.uuid4().hex
        if not parent_id and context.get("trace_id") == trace_id:
            parent_id = context.get("span_id")

        span = Span(
            span_id=uuid.uuid4().hex[:16],
            trace_id=trace_id,
            parent_id=parent_id,
            name=name,
            start_time=time.time(),
            tags=tags or {},
        )

        # 记录根 span
        if not parent_id:
            self._trace_roots[span.trace_id] = span.span_id

        # 存储
        self._spans[span.span_id] = span

        # 容量控制
        if len(self._spans) > self._max_spans:
            self._cleanup_old_spans()

        return span

    def end_span(self, span_id: str, status: SpanStatus = SpanStatus.OK):
        """结束 Span"""
        if span_id in self._spans:
            self._spans[span_id].finish(status)

    def get_span(self, span_id: str) -> Span | None:
        """获取 Span"""
        return self._spans.get(span_id)

    def get_trace(self, trace_id: str) -> list[Span]:
        """获取完整追踪链"""
        return [span for span in self._spans.values() if span.trace_id == trace_id]

    def trace_event(self, event: NeuroEvent, operation: str) -> Span:
        """
        追踪事件处理

        自动从事件元数据提取 trace 信息
        """
        span = self.start_span(
            name=f"{event.event_type}.{operation}",
            trace_id=event.metadata.trace_id,
            parent_id=event.metadata.span_id,
            tags={
                "event_type": event.event_type,
                "domain": event.metadata.domain,
                "priority": event.priority.name,
            },
        )

        # 更新事件的 trace 信息
        event.metadata.trace_id = span.trace_id
        event.metadata.parent_span_id = span.parent_id
        event.metadata.span_id = span.span_id

        return span

    def inject_trace_context(self, event: NeuroEvent) -> NeuroEvent:
        """
        注入追踪上下文到事件

        用于跨服务/领域传播
        """
        context = get_trace_context()
        trace_id = context.get("trace_id")
        span_id = context.get("span_id")

        if trace_id:
            event.metadata.trace_id = trace_id
        if span_id:
            event.metadata.parent_span_id = span_id
            # 生成新的 span_id
            event.metadata.span_id = span_id

        return event

    def get_current_trace_id(self) -> str | None:
        """获取当前 trace_id"""
        return get_trace_context().get("trace_id")

    def get_current_span_id(self) -> str | None:
        """获取当前 span_id"""
        return get_trace_context().get("span_id")

    def _cleanup_old_spans(self):
        """清理旧的 span"""
        # 按开始时间排序，删除最老的 20%
        sorted_spans = sorted(self._spans.items(), key=lambda x: x[1].start_time)
        to_remove = int(len(sorted_spans) * 0.2)

        for span_id, _ in sorted_spans[:to_remove]:
            del self._spans[span_id]

    def get_stats(self) -> dict[str, Any]:
        """获取统计"""
        active_spans = sum(1 for s in self._spans.values() if not s.end_time)
        return {
            "total_spans": len(self._spans),
            "active_spans": active_spans,
            "completed_spans": len(self._spans) - active_spans,
            "traces": len(self._trace_roots),
        }


# 装饰器


def traced(name: str | None = None, tags: dict[str, Any] | None = None):
    """
    追踪装饰器

    用法:
        @traced("process_order")
        async def process_order(order_id: str):
            pass
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            tracer = NeuroTracer()
            span = tracer.start_span(name or func.__name__, tags=tags)
            with span.context():
                try:
                    result = await func(*args, **kwargs)
                except asyncio.CancelledError:
                    span.finish(SpanStatus.CANCELLED)
                    raise
                except BOUNDARY_ERRORS as exc:
                    from app.security.log_redaction import redact_log_text

                    span.set_tag("error.type", type(exc).__name__)
                    span.set_tag("error", redact_log_text(str(exc))[:500])
                    span.finish(SpanStatus.ERROR)
                    raise
                else:
                    span.finish(SpanStatus.OK)
                    return result

        return wrapper

    return decorator
