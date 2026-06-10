"""Tests for the observability primitives + instrumentation wrapper."""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from vibe_coding.agent.observability import (
    AgentObservability,
    Counter,
    Gauge,
    Histogram,
    InMemoryTraceExporter,
    LogRecord,
    MetricsRegistry,
    StructuredLogger,
    Tracer,
    instrument,
    instrument_react_agent,
)


# ---------------------------------------------------- logger


def test_structured_logger_emits_json() -> None:
    captured: list[str] = []
    logger = StructuredLogger(writer=captured.append, level="debug")
    logger.info("evt", "hello", k="v")
    assert len(captured) == 1
    payload = json.loads(captured[0])
    assert payload["event"] == "evt"
    assert payload["msg"] == "hello"
    assert payload["data"]["k"] == "v"
    assert payload["level"] == "info"


def test_logger_filters_below_level() -> None:
    captured: list[str] = []
    logger = StructuredLogger(writer=captured.append, level="warning")
    logger.info("ignored")
    logger.warning("kept")
    assert len(captured) == 1
    assert json.loads(captured[0])["event"] == "kept"


def test_logger_with_context_is_inherited() -> None:
    captured: list[str] = []
    logger = StructuredLogger(writer=captured.append, level="debug")
    child = logger.with_context(project="alpha")
    child.info("hi")
    payload = json.loads(captured[0])
    assert payload["data"]["project"] == "alpha"


def test_logger_attaches_trace_ids_when_bound() -> None:
    captured: list[str] = []
    logger = StructuredLogger(writer=captured.append, level="debug")
    tracer = Tracer(exporters=[InMemoryTraceExporter()])
    logger.bind_tracer(tracer)
    with tracer.start_span("span-A"):
        logger.info("inside_span", "hi")
    payload = json.loads(captured[0])
    assert payload["trace_id"]
    assert payload["span_id"]


def test_logger_capture_buffers_records() -> None:
    logger = StructuredLogger()
    logger.capture(True)
    logger.info("evt", k=1)
    records = logger.captured()
    assert len(records) == 1
    assert isinstance(records[0], LogRecord)
    assert records[0].data["k"] == 1


# ---------------------------------------------------- tracer


def test_tracer_emits_root_span() -> None:
    exporter = InMemoryTraceExporter()
    tracer = Tracer(exporters=[exporter])
    with tracer.start_span("root", attributes={"foo": "bar"}) as span:
        # Sleep long enough to clear the Windows monotonic clock granularity
        # (~15ms) so duration_ms is reliably non-zero.
        time.sleep(0.05)
    spans = exporter.all()
    assert len(spans) == 1
    assert spans[0].name == "root"
    assert spans[0].context.parent_id == ""
    assert spans[0].duration_ms >= 0  # don't depend on the OS clock granularity
    assert spans[0].attributes["foo"] == "bar"
    assert spans[0].status == "ok"


def test_tracer_nested_spans_share_trace_id() -> None:
    exporter = InMemoryTraceExporter()
    tracer = Tracer(exporters=[exporter])
    with tracer.start_span("parent"):
        with tracer.start_span("child"):
            pass
    spans = {s.name: s for s in exporter.all()}
    assert spans["child"].context.trace_id == spans["parent"].context.trace_id
    assert spans["child"].context.parent_id == spans["parent"].context.span_id


def test_tracer_records_exception_status() -> None:
    exporter = InMemoryTraceExporter()
    tracer = Tracer(exporters=[exporter])
    with pytest.raises(RuntimeError):
        with tracer.start_span("boom"):
            raise RuntimeError("kaboom")
    spans = exporter.all()
    assert spans[0].status == "error"
    assert "kaboom" in spans[0].status_message


# ---------------------------------------------------- metrics


def test_counter_inc_and_value() -> None:
    c = Counter(name="x")
    c.inc(2)
    c.inc(3, labels={"k": "v"})
    assert c.value() == 2.0
    assert c.value(labels={"k": "v"}) == 3.0


def test_counter_rejects_negative() -> None:
    c = Counter(name="x")
    with pytest.raises(ValueError):
        c.inc(-1)


def test_gauge_set_and_inc() -> None:
    g = Gauge(name="g")
    g.set(7)
    g.inc(3)
    assert g.value() == 10.0


def test_histogram_observe_and_percentile() -> None:
    h = Histogram(name="h", buckets=(10, 100, 1_000))
    for v in [5, 50, 500, 1500]:
        h.observe(v)
    snap = h.snapshot()[()]
    assert snap["count"] == 4
    assert snap["sum"] == 2055
    # Bucket counts cap at the smallest threshold ``v <= bucket``.
    # 5→bucket(10) 1, 50→bucket(100) 1, 500→bucket(1000) 1, 1500→none.
    assert snap["buckets"] == [1, 1, 1]
    p50 = h.percentile(0.5)
    assert p50 in {50, 500}


def test_metrics_registry_prometheus_export() -> None:
    reg = MetricsRegistry()
    reg.counter("foo_total", description="total foos").inc(2, labels={"x": "y"})
    reg.gauge("queue_depth", description="queue").set(5)
    text = reg.to_prometheus()
    assert "# TYPE foo_total counter" in text
    assert 'foo_total{x="y"} 2' in text
    assert "# TYPE queue_depth gauge" in text


# ---------------------------------------------------- instrumentation


class _FakeCoder:
    def code(self, brief: str) -> dict[str, Any]:
        return {"brief": brief}

    def edit_project(self, brief: str, *, root: str = ".") -> dict[str, Any]:
        return {"brief": brief, "root": root}

    def heal_project(self, brief: str, *, root: str = ".") -> dict[str, Any]:
        raise RuntimeError("boom")


def test_instrument_records_log_span_metric() -> None:
    coder = _FakeCoder()
    metrics = MetricsRegistry()
    tracer_exporter = InMemoryTraceExporter()
    tracer = Tracer(exporters=[tracer_exporter])
    captured: list[str] = []
    logger = StructuredLogger(writer=captured.append, level="debug")
    obs = instrument(
        coder, logger=logger, tracer=tracer, metrics=metrics, component="vibe"
    )
    coder.code("rename foo")
    coder.edit_project("rewrite", root="/tmp/p")
    # Counter went up twice.
    counter = metrics.counters["vibe_action_total"]
    assert counter.value(labels={"method": "code"}) == 1.0
    assert counter.value(labels={"method": "edit_project"}) == 1.0
    # Two spans recorded, each with its own method name.
    span_names = {s.name for s in tracer_exporter.all()}
    assert {"vibe.code", "vibe.edit_project"} <= span_names
    # Logger captured action.start and action.end for each call.
    events = [json.loads(line)["event"] for line in captured]
    assert events.count("action.start") == 2
    assert events.count("action.end") == 2
    # Uninstrumenting restores the originals.
    obs.uninstrument(coder)
    assert coder.code.__name__ == "code"


def test_instrument_records_failures() -> None:
    coder = _FakeCoder()
    metrics = MetricsRegistry()
    tracer_exporter = InMemoryTraceExporter()
    instrument(
        coder,
        metrics=metrics,
        tracer=Tracer(exporters=[tracer_exporter]),
        component="vibe",
    )
    with pytest.raises(RuntimeError):
        coder.heal_project("nope")
    failures = metrics.counters["vibe_action_errors_total"]
    assert failures.value(labels={"method": "heal_project", "error": "RuntimeError"}) == 1.0
    error_spans = [s for s in tracer_exporter.all() if s.status == "error"]
    assert error_spans
    assert "boom" in error_spans[0].status_message


def test_instrument_react_agent_streams_steps() -> None:
    class _Step:
        def __init__(self, idx: int, tool: str) -> None:
            self.index = idx
            self.tool = tool
            self.args = {}
            self.error = ""
            self.duration_ms = 1.5

    class _Agent:
        on_step = None
        tracer = None

    agent = _Agent()
    obs = AgentObservability(
        logger=StructuredLogger(level="debug"),
        tracer=Tracer(exporters=[InMemoryTraceExporter()]),
        metrics=MetricsRegistry(),
    )
    instrument_react_agent(agent, obs)
    agent.tracer(_Step(1, "read_file"), "end")
    agent.on_step(_Step(1, "read_file"))
    counters = obs.metrics.counters["agent_react_step_total"]
    assert counters.value(labels={"tool": "read_file"}) == 1.0
