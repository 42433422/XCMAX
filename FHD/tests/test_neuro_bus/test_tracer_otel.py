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
    mock_tracer.start_as_current_span.return_value.__enter__.return_value = mock_span

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
