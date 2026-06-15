"""Span-based tracer compatible with OpenTelemetry semantic conventions.

The tracer works without any vendor SDK installed: it builds in-memory
:class:`Span` objects and ships them through pluggable
:class:`SpanExporter` implementations. Two exporters are bundled:

- :class:`InMemoryTraceExporter` — keeps the last N spans for the
  Web UI / tests.
- :class:`OTelTraceExporter` — opportunistically forwards spans to
  the user's existing OpenTelemetry pipeline when ``opentelemetry-api``
  is installed. Falls back to a no-op when it isn't.

Span context propagation is thread-local; for asyncio you pass an
explicit parent ``SpanContext`` to :meth:`Tracer.start_span`.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Iterator, Protocol


@dataclass(slots=True)
class SpanContext:
    """Identifiers carried with every span."""

    trace_id: str
    span_id: str
    parent_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Span:
    """One span; serialisable to OTLP/JSON shape."""

    name: str
    context: SpanContext
    start_ns: int
    end_ns: int = 0
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    status: str = "unset"
    status_message: str = ""

    @property
    def duration_ms(self) -> float:
        if self.end_ns == 0:
            return 0.0
        return round((self.end_ns - self.start_ns) / 1_000_000, 3)

    def add_event(self, name: str, **attrs: Any) -> None:
        self.events.append(
            {
                "name": name,
                "time_ns": time.monotonic_ns(),
                "attributes": dict(attrs),
            }
        )

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def set_status(self, status: str, message: str = "") -> None:
        self.status = status
        self.status_message = message

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "trace_id": self.context.trace_id,
            "span_id": self.context.span_id,
            "parent_id": self.context.parent_id,
            "start_ns": int(self.start_ns),
            "end_ns": int(self.end_ns),
            "duration_ms": self.duration_ms,
            "attributes": dict(self.attributes),
            "events": list(self.events),
            "status": self.status,
            "status_message": self.status_message,
        }


class SpanExporter(Protocol):
    def export(self, span: Span) -> None: ...

    def shutdown(self) -> None: ...


# ----------------------------------------------------- exporters


class InMemoryTraceExporter:
    """Keeps the most recent ``capacity`` spans in memory."""

    def __init__(self, capacity: int = 1024) -> None:
        self._spans: deque[Span] = deque(maxlen=int(capacity))
        self._lock = threading.Lock()

    def export(self, span: Span) -> None:
        with self._lock:
            self._spans.append(span)

    def shutdown(self) -> None:
        return None

    def all(self) -> list[Span]:
        with self._lock:
            return list(self._spans)

    def clear(self) -> None:
        with self._lock:
            self._spans.clear()


class OTelTraceExporter:
    """Forward spans to OpenTelemetry when the SDK is installed.

    Best-effort — when ``opentelemetry-api`` is missing this becomes a
    no-op so user code stays portable.
    """

    def __init__(self, *, service_name: str = "vibe-coding") -> None:
        self.service_name = service_name
        self._tracer = None
        self._available: bool | None = None

    def export(self, span: Span) -> None:
        if not self._ensure_tracer():
            return
        # Reproduce the shape OTel expects: a started span with attributes,
        # events, status. We use the API only — no SDK dependency.
        try:
            from opentelemetry import trace as otel_trace  # type: ignore[import-not-found]
            from opentelemetry.trace import Status, StatusCode  # type: ignore[import-not-found]

            tracer = otel_trace.get_tracer(self.service_name)
            with tracer.start_as_current_span(span.name) as otel_span:  # type: ignore[union-attr]
                for k, v in span.attributes.items():
                    otel_span.set_attribute(k, v)
                for evt in span.events:
                    otel_span.add_event(
                        evt.get("name", ""), attributes=dict(evt.get("attributes") or {})
                    )
                if span.status == "error":
                    otel_span.set_status(Status(StatusCode.ERROR, span.status_message))
        except Exception:  # noqa: BLE001
            pass

    def shutdown(self) -> None:
        return None

    def _ensure_tracer(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            import opentelemetry.trace  # type: ignore[import-not-found]  # noqa: F401

            self._available = True
        except ImportError:
            self._available = False
        return self._available


# ----------------------------------------------------- tracer


class Tracer:
    """Span-based tracer with thread-local context propagation."""

    def __init__(
        self,
        *,
        service_name: str = "vibe-coding",
        exporters: list[SpanExporter] | None = None,
    ) -> None:
        self.service_name = service_name
        self._exporters = list(exporters or [InMemoryTraceExporter()])
        self._local = threading.local()

    @property
    def exporters(self) -> list[SpanExporter]:
        return list(self._exporters)

    def add_exporter(self, exporter: SpanExporter) -> None:
        self._exporters.append(exporter)

    @contextlib.contextmanager
    def start_span(
        self,
        name: str,
        *,
        parent: SpanContext | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Iterator[Span]:
        ctx = self._build_context(parent)
        span = Span(
            name=name,
            context=ctx,
            start_ns=time.monotonic_ns(),
            attributes=dict(attributes or {}),
        )
        prev = getattr(self._local, "current", None)
        self._local.current = ctx
        try:
            yield span
            if span.status == "unset":
                span.set_status("ok")
        except Exception as exc:
            span.set_status("error", f"{type(exc).__name__}: {exc}")
            span.set_attribute("exception.type", type(exc).__name__)
            span.set_attribute("exception.message", str(exc))
            raise
        finally:
            span.end_ns = time.monotonic_ns()
            for exporter in self._exporters:
                try:
                    exporter.export(span)
                except Exception:  # noqa: BLE001
                    pass
            self._local.current = prev

    def current_context(self) -> SpanContext | None:
        return getattr(self._local, "current", None)

    def shutdown(self) -> None:
        for exporter in self._exporters:
            try:
                exporter.shutdown()
            except Exception:  # noqa: BLE001
                pass

    # ----------------------------------------------------------- internals

    def _build_context(self, parent: SpanContext | None) -> SpanContext:
        current = parent or self.current_context()
        if current is None:
            return SpanContext(trace_id=_make_trace_id(), span_id=_make_span_id())
        return SpanContext(
            trace_id=current.trace_id,
            span_id=_make_span_id(),
            parent_id=current.span_id,
        )


# ----------------------------------------------------- helpers


def _make_trace_id() -> str:
    return uuid.uuid4().hex


def _make_span_id() -> str:
    return uuid.uuid4().hex[:16]


# ----------------------------------------------------- singleton


_DEFAULT: Tracer | None = None
_DEFAULT_LOCK = threading.Lock()


def get_default_tracer() -> Tracer:
    """Lazy process-wide tracer; respects ``VIBE_OTEL_ENABLED`` env var."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            exporters: list[SpanExporter] = [InMemoryTraceExporter()]
            if os.environ.get("VIBE_OTEL_ENABLED", "").lower() in {"1", "true", "yes"}:
                exporters.append(OTelTraceExporter())
            _DEFAULT = Tracer(exporters=exporters)
        return _DEFAULT


__all__ = [
    "InMemoryTraceExporter",
    "OTelTraceExporter",
    "Span",
    "SpanContext",
    "SpanExporter",
    "Tracer",
    "get_default_tracer",
]
