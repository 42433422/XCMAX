"""Tracer OTel 集成测试。"""

import sys
from unittest.mock import MagicMock, patch

import pytest


def test_span_creates_without_otel(monkeypatch):
    """OTel SDK 不可用时，Span 退化为内存对象。"""
    # 模拟 OTel 不可用
    monkeypatch.setitem(sys.modules, "opentelemetry", None)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", None)

    from app.neuro_bus.tracer import Span, SpanStatus

    span = Span(
        span_id="",
        trace_id="trace-1",
        parent_id=None,
        name="test.op",
        start_time=0.0,
    )
    assert span.span_id  # 自动生成
    assert span.status == SpanStatus.OK
    span.set_tag("key", "value")
    assert span.tags["key"] == "value"
    span.add_event("event1", {"attr": 1})
    assert len(span.events) == 1
    span.finish()
    assert span.end_time is not None


def test_span_finish_sets_status_error():
    """finish(ERROR) 设置错误状态。"""
    from app.neuro_bus.tracer import Span, SpanStatus

    span = Span(
        span_id="s1",
        trace_id="t1",
        parent_id=None,
        name="test.fail",
        start_time=0.0,
    )
    span.finish(SpanStatus.ERROR)
    assert span.status == SpanStatus.ERROR


def test_span_duration_ms():
    """duration_ms 正确计算。"""
    from app.neuro_bus.tracer import Span

    span = Span(
        span_id="s1",
        trace_id="t1",
        parent_id=None,
        name="test.dur",
        start_time=100.0,
    )
    span.end_time = 100.5
    assert span.duration_ms == 500.0


def test_span_delegates_to_otel_when_available(monkeypatch):
    """OTel 可用时，Span 委托给 OTel SDK。"""
    # 创建 mock OTel 模块
    mock_span = MagicMock()
    mock_tracer = MagicMock()
    mock_tracer.start_span.return_value = mock_span

    mock_trace = MagicMock()
    mock_trace.get_tracer.return_value = mock_tracer

    mock_otel = MagicMock()
    mock_otel.trace = mock_trace

    monkeypatch.setitem(sys.modules, "opentelemetry", mock_otel)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", mock_trace)

    from app.neuro_bus.tracer import Span

    span = Span(
        span_id="",
        trace_id="t1",
        parent_id=None,
        name="otel.test",
        start_time=0.0,
    )
    span.set_tag("env", "test")
    span.add_event("started", {"k": 1})
    span.finish()

    mock_span.set_attribute.assert_called_with("env", "test")
    mock_span.add_event.assert_called_with("started", {"k": 1})
    mock_span.end.assert_called_once()


def test_span_uses_monotonic_clock_and_finishes_once(monkeypatch):
    from types import SimpleNamespace

    from app.neuro_bus import tracer

    ticks = [100_000_000]
    monkeypatch.setattr(
        tracer, "time", SimpleNamespace(time=lambda: 10.0, perf_counter_ns=lambda: ticks[0])
    )
    span = tracer.Span("a" * 16, "b" * 32, None, "clock", start_time=1000.0)
    span._started_ns = ticks[0]
    ticks[0] += 50_000_000
    span.finish(tracer.SpanStatus.ERROR)
    ticks[0] += 90_000_000
    span.finish(tracer.SpanStatus.OK)
    assert span.duration_ms == 50
    assert span.status == tracer.SpanStatus.ERROR


def test_context_unifies_otel_and_restores_parent():
    from opentelemetry import trace

    from app.neuro_bus.tracer import TraceContext, get_trace_context

    before = get_trace_context()
    with TraceContext("a" * 32, "b" * 16, request_id="request-1") as parent:
        assert trace.get_current_span().get_span_context().trace_id == int("a" * 32, 16)
        with TraceContext(parent.trace_id, "c" * 16):
            assert get_trace_context() == {
                "trace_id": "a" * 32,
                "span_id": "c" * 16,
                "request_id": "request-1",
                "trace_flags": "01",
            }
        assert get_trace_context()["span_id"] == "b" * 16
    assert get_trace_context() == before


def test_native_otel_span_ids_and_error_status_are_shared(monkeypatch):
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from app.neuro_bus.tracer import NeuroTracer, SpanStatus, TraceContext

    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(trace, "get_tracer", lambda *a, **kw: provider.get_tracer("test"))
    try:
        with TraceContext("a" * 32, "b" * 16):
            span = NeuroTracer().start_span("child")
            assert span._otel_span.get_span_context().trace_id == int(span.trace_id, 16)
            assert span._otel_span.get_span_context().span_id == int(span.span_id, 16)
            span.finish(SpanStatus.ERROR)
        exported = exporter.get_finished_spans()[0]
        assert exported.parent.span_id == int("b" * 16, 16)
        assert exported.status.status_code == trace.StatusCode.ERROR
    finally:
        provider.shutdown()


def test_start_span_does_not_leak_context_when_finished_elsewhere():
    from concurrent.futures import ThreadPoolExecutor

    from app.neuro_bus.tracer import NeuroTracer, TraceContext, get_trace_context

    with TraceContext("a" * 32, "b" * 16):
        before = get_trace_context()
        tracer = NeuroTracer()
        first = tracer.start_span("publish-one")
        second = tracer.start_span("publish-two")
        assert first.parent_id == second.parent_id == "b" * 16
        assert first.span_id != second.span_id
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(first.finish).result()
        second.finish()
        assert get_trace_context() == before


@pytest.mark.parametrize("cancelled", [False, True])
async def test_decorator_restores_context_on_error_and_cancellation(monkeypatch, cancelled):
    import asyncio

    from app.neuro_bus import tracer

    recorder = tracer.NeuroTracer()
    monkeypatch.setattr(tracer, "NeuroTracer", lambda: recorder)
    before = tracer.get_trace_context()

    @tracer.traced("work")
    async def work():
        assert tracer.get_trace_context()["trace_id"]
        if cancelled:
            raise asyncio.CancelledError
        raise TypeError("api_key=secret-value")

    with pytest.raises(asyncio.CancelledError if cancelled else TypeError):
        await work()
    span = next(iter(recorder._spans.values()))
    assert span.status == (tracer.SpanStatus.CANCELLED if cancelled else tracer.SpanStatus.ERROR)
    assert "secret-value" not in str(span.tags)
    assert tracer.get_trace_context() == before


@pytest.mark.parametrize(
    "method", ["start_span", "get_span_context", "set_status", "add_event", "set_attribute", "end"]
)
async def test_otel_failure_does_not_override_business_result(monkeypatch, method):
    from opentelemetry import trace

    from app.neuro_bus import tracer

    broken = MagicMock()
    getattr(broken, method).side_effect = RuntimeError("exporter unavailable")
    backend = MagicMock()
    backend.start_span = (
        broken.start_span if method == "start_span" else MagicMock(return_value=broken)
    )
    monkeypatch.setattr(trace, "get_tracer", lambda *a, **kw: backend)
    recorder = tracer.NeuroTracer()
    monkeypatch.setattr(tracer, "NeuroTracer", lambda: recorder)

    @tracer.traced("success")
    async def succeed():
        span = next(iter(recorder._spans.values()))
        span.add_event("start")
        span.set_tag("phase", "test")
        return "business-result"

    assert await succeed() == "business-result"
    failure = ValueError("original business failure")

    @tracer.traced("failure")
    async def fail():
        raise failure

    with pytest.raises(ValueError) as exc:
        await fail()
    assert exc.value is failure
