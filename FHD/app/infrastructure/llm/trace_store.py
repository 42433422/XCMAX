"""GenAI span 本地 JSONL 存储：日轮转、保留期清理、后台 flush、可选 OTLP 双写。

- 存储目录默认 ``<log_dir>/genai_traces``（桌面端自动落 %APPDATA%\\XCAGI\\logs）。
- 写入经内存队列 + 后台线程 flush，LLM 调用链路零阻塞；一切异常 fail-open。
- 设置 XCAGI_OTLP_ENDPOINT 时对每条 span 双写 OTLP（依赖已在 requirements）。
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


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
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=2000)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._otlp_exporter: Any | None = None
        self._otlp_failed = False

    # ---- 写入 ----

    def record(self, span_dict: dict[str, Any]) -> None:
        """入队（永不抛异常）。队列有上限，满时丢掉最旧的一条。"""
        try:
            self._queue.put_nowait(span_dict)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return
            try:
                self._queue.put_nowait(span_dict)
            except queue.Full:
                return
        except RECOVERABLE_ERRORS:
            logger.warning("genai trace enqueue failed", exc_info=True)

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._flush_loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)
        self.flush()

    def _flush_loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(1.0)
            self.flush()

    def flush(self) -> None:
        """排空队列写入当日文件（fail-open）。"""
        batch: list[dict[str, Any]] = []
        while len(batch) < self._max_batch:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if not batch:
            return
        try:
            self._base_dir.mkdir(parents=True, exist_ok=True)
            path = self._daily_file(date.today())
            with path.open("a", encoding="utf-8") as fh:
                for item in batch:
                    fh.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
        except RECOVERABLE_ERRORS:
            logger.warning("genai trace flush failed", exc_info=True)
        for item in batch:
            self._export_otlp(item)

    def _daily_file(self, day: date) -> Path:
        return self._base_dir / f"trace-{day.isoformat()}.jsonl"

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
        items: list[dict[str, Any]] = []
        try:
            files = sorted(self._base_dir.glob("trace-*.jsonl"), reverse=True)
            for path in files:
                for line in path.read_text(encoding="utf-8").splitlines():
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not self._matches(
                        item,
                        trace_id=trace_id,
                        model=model,
                        status=status,
                        since=since,
                        until=until,
                        has_guardrail_block=has_guardrail_block,
                    ):
                        continue
                    items.append(item)
        except RECOVERABLE_ERRORS:
            logger.warning("genai trace query failed", exc_info=True)
        items.sort(key=lambda x: x.get("start_time") or 0, reverse=True)
        return items[:limit]

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
        if trace_id and item.get("trace_id") != trace_id:
            return False
        if model and attrs.get("gen_ai.request.model") != model:
            return False
        if status and item.get("status") != status:
            return False
        start = item.get("start_time") or 0
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

    def _export_otlp(self, span_dict: dict[str, Any]) -> None:
        endpoint = (os.environ.get("XCAGI_OTLP_ENDPOINT") or "").strip()
        if not endpoint or self._otlp_failed:
            return
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import Event, ReadableSpan
            from opentelemetry.sdk.trace.export import SpanExportResult
            from opentelemetry.sdk.util.instrumentation import InstrumentationScope

            from app.neuro_bus.tracer import otel_context

            # Flush happens off-thread. Export the original span, never create a new trace.
            context = otel_context(
                span_dict.get("trace_id"),
                span_dict.get("span_id"),
                trace_flags=span_dict.get("trace_flags", "01"),
                trace_state=span_dict.get("trace_state", ""),
            )
            if context is None or span_dict.get("end_time") is None:
                return
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
            failed = span_dict.get("status") == "error"
            span = ReadableSpan(
                name=span_dict.get("name") or "chat",
                context=span_context,
                parent=parent,
                resource=Resource.create({"service.name": "xcagi.genai"}),
                instrumentation_scope=InstrumentationScope("xcagi.genai"),
                kind=trace.SpanKind.CLIENT,
                start_time=started,
                end_time=started + elapsed,
                status=trace.Status(trace.StatusCode.ERROR if failed else trace.StatusCode.UNSET),
                attributes=span_dict.get("attributes") or {},
                events=[
                    Event(
                        event["name"],
                        attributes=event.get("attributes") or {},
                        timestamp=int(float(event["timestamp"]) * 1_000_000_000),
                    )
                    for event in span_dict.get("events") or []
                ],
            )
            exporter = self._get_otlp_exporter(endpoint)
            if exporter is not None and exporter.export((span,)) != SpanExportResult.SUCCESS:
                logger.warning("OTLP export failed; local trace retained")
        except BOUNDARY_ERRORS:
            self._otlp_failed = True
            logger.warning("OTLP export disabled after failure")

    def _get_otlp_exporter(self, endpoint: str) -> Any | None:
        if self._otlp_exporter is None:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            self._otlp_exporter = OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
        return self._otlp_exporter


_store: TraceStore | None = None
_store_lock = threading.Lock()


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
    """测试专用：停掉并清空单例。"""
    global _store
    with _store_lock:
        if _store is not None:
            _store.stop()
        _store = None
