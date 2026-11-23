"""Existing JSONL trace view and OTLP transport, batched by the pinned OTel SDK."""

from __future__ import annotations

import heapq
import json
import logging
import math
import os
import threading
from collections.abc import Callable, Iterator, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from opentelemetry.sdk._logs import LoggerProvider, ReadableLogRecord
from opentelemetry.sdk._logs.export import (
    BatchLogRecordProcessor,
    LogRecordExporter,
    LogRecordExportResult,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)

from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class _JsonlExporter(LogRecordExporter):
    """The only product-specific sink: preserve the existing queryable JSONL shape."""

    def __init__(self, base_dir: Path, cleanup: Callable[[], None]) -> None:
        self.base_dir = base_dir
        self.cleanup = cleanup
        self._day: date | None = None

    def export(self, batch: Sequence[ReadableLogRecord]) -> LogRecordExportResult:
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            day = date.today()
            if day != self._day:
                self.cleanup()
                self._day = day
            path = self.base_dir / f"trace-{day.isoformat()}.jsonl"
            with path.open("a", encoding="utf-8") as stream:
                for record in batch:
                    stream.write(str(record.log_record.body) + "\n")
        except RECOVERABLE_ERRORS:
            logger.warning("genai trace flush failed", exc_info=True)
            return LogRecordExportResult.FAILURE
        return LogRecordExportResult.SUCCESS

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


class _LocalSpanExporter(SpanExporter):
    """SDK tool/NeuroBus spans share the existing local trace view."""

    def __init__(self, record: Callable[[dict[str, Any]], None]) -> None:
        self.record = record

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        from opentelemetry.trace import StatusCode

        for span in spans:
            context = span.context
            if context is None or span.start_time is None or span.end_time is None:
                continue
            self.record(
                {
                    "trace_id": format(context.trace_id, "032x"),
                    "span_id": format(context.span_id, "016x"),
                    "parent_span_id": format(span.parent.span_id, "016x") if span.parent else None,
                    "trace_flags": format(context.trace_flags, "02x"),
                    "trace_state": context.trace_state.to_header(),
                    "name": span.name,
                    "start_time": span.start_time / 1_000_000_000,
                    "end_time": span.end_time / 1_000_000_000,
                    "duration_ms": (span.end_time - span.start_time) / 1_000_000,
                    "status": "cancelled"
                    if (span.attributes or {}).get("xcagi.cancelled")
                    else "error"
                    if span.status.status_code == StatusCode.ERROR
                    else "ok",
                    "attributes": dict(span.attributes or {}),
                    "events": [
                        {
                            "name": event.name,
                            "timestamp": event.timestamp / 1_000_000_000,
                            "attributes": dict(event.attributes or {}),
                        }
                        for event in span.events
                    ],
                }
            )
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass


def _retention_days() -> int:
    raw = (os.environ.get("XCAGI_GENAI_TRACE_RETENTION_DAYS") or "").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 14


def _default_base_dir() -> Path:
    explicit = (os.environ.get("XCAGI_GENAI_TRACE_DIR") or "").strip()
    if explicit:
        return Path(explicit)
    from app.utils.path_io.path_utils import get_log_dir

    return Path(get_log_dir()) / "genai_traces"


class TraceStore:
    """append-only JSONL span 存储。"""

    def __init__(
        self,
        base_dir: Path | None = None,
        *,
        retention_days: int | None = None,
        max_batch: int = 100,
    ) -> None:
        self._base_dir = base_dir or _default_base_dir()
        self._retention_days = retention_days if retention_days is not None else _retention_days()
        self._max_batch = max_batch
        self._lock = threading.RLock()
        self._closed = False
        self._log_provider: LoggerProvider | None = None
        self._provider: TracerProvider | None = None
        self._otlp_processor: BatchSpanProcessor | None = None

    # ---- 写入 ----

    def record(self, span_dict: dict[str, Any]) -> None:
        """Snapshot locally and enqueue sampled OTLP spans without network I/O."""
        try:
            with self._lock:
                if self._closed:
                    return
                self.start()
                self._record_local(span_dict)
                if self._otlp_processor is not None:
                    span = self._readable_span(span_dict)
                    if span is not None:
                        self._otlp_processor.on_end(span)
        except BOUNDARY_ERRORS:
            logger.warning("genai trace enqueue failed", exc_info=True)

    def _record_local(self, span_dict: dict[str, Any]) -> None:
        with self._lock:
            if self._log_provider is not None:
                # An immutable body keeps queued records independent of later mutations.
                self._log_provider.get_logger("xcagi.genai").emit(
                    body=json.dumps(span_dict, ensure_ascii=False, default=str)
                )

    def start(self) -> None:
        with self._lock:
            if self._provider is not None:
                return
            resource = Resource.create({"service.name": "xcagi.genai"})
            self._log_provider = LoggerProvider(resource=resource)
            self._log_provider.add_log_record_processor(
                BatchLogRecordProcessor(
                    _JsonlExporter(self._base_dir, self.cleanup_expired),
                    max_queue_size=2000,
                    max_export_batch_size=self._max_batch,
                    schedule_delay_millis=1000,
                )
            )
            self._provider = TracerProvider(resource=resource)
            self._provider.add_span_processor(
                SimpleSpanProcessor(_LocalSpanExporter(self._record_local))
            )
            self._closed = False
            endpoint = (os.environ.get("XCAGI_OTLP_ENDPOINT") or "").strip()
            if endpoint:
                try:
                    self._otlp_processor = BatchSpanProcessor(
                        self._get_otlp_exporter(endpoint),
                        max_queue_size=2000,
                        max_export_batch_size=self._max_batch,
                        schedule_delay_millis=1000,
                    )
                    self._provider.add_span_processor(self._otlp_processor)
                except BOUNDARY_ERRORS:
                    logger.warning(
                        "OTLP initialization failed; local traces remain available", exc_info=True
                    )

    @property
    def tracer_provider(self) -> TracerProvider:
        with self._lock:
            self.start()
            assert self._provider is not None
            return self._provider

    def stop(self) -> None:
        with self._lock:
            self._closed = True
            provider, logs = self._provider, self._log_provider
            self._provider = self._log_provider = self._otlp_processor = None
        # SDK shutdown drains every queued batch and closes the exporters.
        try:
            if provider is not None:
                provider.shutdown()
        finally:
            if logs is not None:
                logs.shutdown()

    def flush(self) -> None:
        """Drain the SDK queues; exporters remain usable after transient failure."""
        with self._lock:
            provider, logs = self._provider, self._log_provider
        for target in (logs, provider):
            if target is not None and not target.force_flush(timeout_millis=5000):
                logger.warning("genai trace flush deadline exceeded")

    # ---- 保留期 ----

    def cleanup_expired(self) -> None:
        cutoff = date.today() - timedelta(days=self._retention_days)
        try:
            for path in self._base_dir.glob("trace-*.jsonl"):
                try:
                    day = date.fromisoformat(path.stem.removeprefix("trace-"))
                except ValueError:
                    continue
                if day < cutoff:
                    path.unlink(missing_ok=True)
        except RECOVERABLE_ERRORS:
            logger.warning("genai trace cleanup failed", exc_info=True)

    # ---- 查询 ----

    def query(
        self,
        *,
        trace_id: str | None = None,
        model: str | None = None,
        status: str | None = None,
        since: float | None = None,
        until: float | None = None,
        has_guardrail_block: bool | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        def records() -> Iterator[dict[str, Any]]:
            for path in sorted(self._base_dir.glob("trace-*.jsonl"), reverse=True):
                try:
                    with path.open(encoding="utf-8") as stream:
                        for line in stream:
                            try:
                                item = json.loads(line)
                                if not isinstance(item, dict) or not self._matches(
                                    item,
                                    trace_id=trace_id,
                                    model=model,
                                    status=status,
                                    since=since,
                                    until=until,
                                    has_guardrail_block=has_guardrail_block,
                                ):
                                    continue
                            except (ValueError, TypeError):
                                continue
                            yield item
                except RECOVERABLE_ERRORS:
                    logger.warning("genai trace query failed", exc_info=True)

        # Keep only the requested newest records even after weeks of continuous use.
        return heapq.nlargest(
            max(0, limit), records(), key=lambda item: item.get("start_time") or 0
        )

    @staticmethod
    def _matches(
        item: dict[str, Any],
        *,
        trace_id: str | None,
        model: str | None,
        status: str | None,
        since: float | None,
        until: float | None,
        has_guardrail_block: bool | None,
    ) -> bool:
        attrs = item.get("attributes") or {}
        if not isinstance(attrs, dict):
            return False
        if trace_id and item.get("trace_id") != trace_id:
            return False
        if model and attrs.get("gen_ai.request.model") != model:
            return False
        if status and item.get("status") != status:
            return False
        start = item.get("start_time") or 0
        if not isinstance(start, (int, float)) or not math.isfinite(start):
            return False
        if since is not None and start < since:
            return False
        if until is not None and start > until:
            return False
        if (
            has_guardrail_block is not None
            and bool(attrs.get("guardrail.blocked")) != has_guardrail_block
        ):
            return False
        return True

    # ---- OTLP 双写 ----

    def _readable_span(self, span_dict: dict[str, Any]) -> ReadableSpan | None:
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.trace import Event
            from opentelemetry.sdk.util.instrumentation import InstrumentationScope

            from app.neuro_bus.tracer import otel_context

            # Transport happens off-thread; keep the original span and cached SDK resource.
            context = otel_context(
                span_dict.get("trace_id"),
                span_dict.get("span_id"),
                trace_flags=span_dict.get("trace_flags", "01"),
                trace_state=span_dict.get("trace_state", ""),
            )
            if context is None or span_dict.get("end_time") is None:
                return None
            original = trace.get_current_span(context).get_span_context()
            span_context = trace.SpanContext(
                original.trace_id,
                original.span_id,
                is_remote=False,
                trace_flags=original.trace_flags,
                trace_state=original.trace_state,
            )
            parent_context = otel_context(
                span_dict.get("trace_id"),
                span_dict.get("parent_span_id"),
                trace_flags=span_dict.get("trace_flags", "01"),
                trace_state=span_dict.get("trace_state", ""),
            )
            parent = (
                trace.get_current_span(parent_context).get_span_context()
                if parent_context
                else None
            )
            started = int(float(span_dict["start_time"]) * 1_000_000_000)
            duration = span_dict.get("duration_ms")
            elapsed = (
                max(0, int(float(duration) * 1_000_000))
                if duration is not None
                else max(0, int(float(span_dict["end_time"]) * 1_000_000_000) - started)
            )
            failed = span_dict.get("status") in {"error", "cancelled"}
            return ReadableSpan(
                name=span_dict.get("name") or "chat",
                context=span_context,
                parent=parent,
                resource=self.tracer_provider.resource,
                instrumentation_scope=InstrumentationScope("xcagi.genai"),
                kind=trace.SpanKind.CLIENT,
                start_time=started,
                end_time=started + elapsed,
                status=trace.Status(trace.StatusCode.ERROR if failed else trace.StatusCode.UNSET),
                attributes=_otel_attributes(span_dict.get("attributes") or {}),
                events=[
                    Event(
                        event["name"],
                        attributes=_otel_attributes(event.get("attributes") or {}),
                        timestamp=int(float(event["timestamp"]) * 1_000_000_000),
                    )
                    for event in span_dict.get("events") or []
                ],
            )
        except BOUNDARY_ERRORS:
            logger.warning("invalid OTLP span; local trace retained", exc_info=True)
            return None

    def _get_otlp_exporter(self, endpoint: str) -> SpanExporter:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        url = endpoint.rstrip("/")
        if not url.endswith("/v1/traces"):
            url += "/v1/traces"
        return OTLPSpanExporter(endpoint=url, timeout=5)


def _otel_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    """OTel scalar/array attributes cannot encode the local content descriptor dict."""
    return {
        key: json.dumps(value, ensure_ascii=False, default=str)
        if isinstance(value, dict)
        else value
        for key, value in attributes.items()
        if value is not None
    }


_store: TraceStore | None = None
_store_lock = threading.Lock()


def get_runtime_tracer(name: str) -> Any:
    """Use the application-owned SDK without replacing a process global provider."""
    from opentelemetry import trace

    from app.infrastructure.llm.genai_telemetry import trace_enabled

    if not trace_enabled():
        return trace.NoOpTracer()
    return trace.get_tracer(name, tracer_provider=get_trace_store().tracer_provider)


def get_trace_store() -> TraceStore:
    """惰性单例：首次使用启动后台 flush 并清理过期文件。"""
    global _store
    with _store_lock:
        if _store is None:
            _store = TraceStore()
            _store.cleanup_expired()
            _store.start()
        return _store


def reset_trace_store() -> None:
    """Release the process-owned SDK processors; the next lifespan starts cleanly."""
    global _store
    with _store_lock:
        if _store is not None:
            _store.stop()
        _store = None
