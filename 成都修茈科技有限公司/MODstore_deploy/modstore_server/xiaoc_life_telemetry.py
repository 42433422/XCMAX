"""Instrument the existing life runtime; no new scheduler or execution authority."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from prometheus_client import Counter, Gauge, Histogram

STAGES = frozenset({"tick", "reconcile", "graph", "observe", "decide", "act", "reflect", "settle"})
OPERATIONS = Counter(
    "modstore_xiaoc_life_operations_total",
    "Life runtime operation returns, errors and cancellations (not business outcomes).",
    ("stage", "outcome"),
)
ACTIVE = Gauge(
    "modstore_xiaoc_life_active_operations",
    "Current life runtime operations in this process.",
    ("stage",),
)
DURATION = Histogram(
    "modstore_xiaoc_life_operation_duration_seconds",
    "Life runtime operation wall-clock duration.",
    ("stage",),
    buckets=(0.01, 0.1, 0.5, 1, 5, 15, 30, 60, 120, 300, 600),
)


@contextmanager
def life_operation(stage: str) -> Iterator[None]:
    if stage not in STAGES:
        raise ValueError("unknown life runtime telemetry stage")
    started = perf_counter()
    gauge = ACTIVE.labels(stage)
    gauge.inc()
    outcome = "error"
    try:
        tracer = trace.get_tracer("modstore.xiaoc.life")
        with tracer.start_as_current_span(
            f"xiaoc.life.{stage}", record_exception=False, set_status_on_exception=False
        ) as span:
            try:
                yield
            except asyncio.CancelledError:
                outcome = "cancelled"
                span.set_status(Status(StatusCode.ERROR))
                raise
            except Exception:
                span.set_status(Status(StatusCode.ERROR))
                raise
            else:
                outcome = "returned"
            finally:
                # Fixed vocabulary only: no IDs, prompts, secrets or error text.
                span.set_attribute("xiaoc.stage", stage)
                span.set_attribute("xiaoc.outcome", outcome)
    finally:
        gauge.dec()
        OPERATIONS.labels(stage, outcome).inc()
        DURATION.labels(stage).observe(perf_counter() - started)
