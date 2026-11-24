"""Instrument the existing life runtime; no new scheduler or execution authority."""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
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

PROCESS_CPU_SECONDS = Gauge(
    "modstore_xiaoc_life_process_cpu_seconds",
    "CPU seconds consumed by this worker process.",
)
PROCESS_RSS_BYTES = Gauge(
    "modstore_xiaoc_life_process_rss_bytes",
    "Current resident bytes of this worker on supported Linux hosts.",
)
PROCESS_OPEN_FDS = Gauge(
    "modstore_xiaoc_life_process_open_fds",
    "Currently open Linux file descriptors in this worker.",
)


def observe_process_resources() -> None:
    """Process-local observations, never claims about other server workers."""
    usage = os.times()
    PROCESS_CPU_SECONDS.set(usage.user + usage.system)
    if sys.platform == "linux":
        try:
            with open("/proc/self/statm", encoding="ascii") as stream:
                pages = int(stream.readline().split()[1])
            PROCESS_RSS_BYTES.set(pages * os.sysconf("SC_PAGE_SIZE"))
            PROCESS_OPEN_FDS.set(len(os.listdir("/proc/self/fd")))
        except (OSError, ValueError, IndexError):
            # A missing /proc is an unavailable metric, not a business failure.
            return


@contextmanager
def life_operation(stage: str, *, cycle_id: str | None = None) -> Iterator[None]:
    if stage not in STAGES:
        raise ValueError("unknown life runtime telemetry stage")
    if cycle_id is not None and (not isinstance(cycle_id, str) or not 0 < len(cycle_id) <= 96):
        raise ValueError("invalid trace cycle identity")
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
                if cycle_id is not None:
                    # Correlate across nodes without exporting raw tenant IDs.
                    span.set_attribute(
                        "xiaoc.cycle_sha256", hashlib.sha256(cycle_id.encode()).hexdigest()
                    )
    finally:
        gauge.dec()
        OPERATIONS.labels(stage, outcome).inc()
        DURATION.labels(stage).observe(perf_counter() - started)
        if stage == "tick":
            observe_process_resources()
