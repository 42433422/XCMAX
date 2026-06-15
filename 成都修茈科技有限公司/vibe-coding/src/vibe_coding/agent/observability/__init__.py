"""Observability primitives — structured logs + tracing + metrics.

Three minimal layers, all zero-dep so they always import:

- :class:`StructuredLogger` — JSON-line logs with run / span context
  baked into every record. Adapts to any sink (stderr by default,
  file, Loki, …) via a ``writer`` callable.
- :class:`Tracer` — span-based tracing API that mirrors the
  OpenTelemetry semantic conventions. When OTel is installed the
  ``OTelTracer`` exporter forwards spans to your existing pipeline;
  otherwise the in-memory exporter feeds the Web UI dashboard.
- :class:`MetricsRegistry` — counters + histograms for the common
  agent dashboards (skill generations, repair attempts, sandbox
  durations). Prometheus exposition format is provided out of the
  box for ``/metrics`` scrapers.

Use :func:`instrument` to attach all three to a :class:`VibeCoder`
instance — every public method gets a log + span + metric without the
caller having to thread context manually.
"""

from __future__ import annotations

from .instrumentation import (
    AgentObservability,
    instrument,
    instrument_react_agent,
)
from .logging import LogRecord, StructuredLogger, get_default_logger
from .metrics import (
    Counter,
    Gauge,
    Histogram,
    MetricsRegistry,
    get_default_registry,
)
from .tracing import (
    InMemoryTraceExporter,
    OTelTraceExporter,
    Span,
    SpanContext,
    Tracer,
    get_default_tracer,
)

__all__ = [
    "AgentObservability",
    "Counter",
    "Gauge",
    "Histogram",
    "InMemoryTraceExporter",
    "LogRecord",
    "MetricsRegistry",
    "OTelTraceExporter",
    "Span",
    "SpanContext",
    "StructuredLogger",
    "Tracer",
    "get_default_logger",
    "get_default_registry",
    "get_default_tracer",
    "instrument",
    "instrument_react_agent",
]
