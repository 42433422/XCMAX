"""Tracer OTel 集成测试。"""
import sys
from unittest.mock import patch

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
