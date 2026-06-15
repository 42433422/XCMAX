"""Structured JSON logging.

We don't want to drag the stdlib ``logging`` machinery into the agent's
hot path — it's powerful but slow and global-state-heavy. The logger
here is a thin JSON-line emitter that:

- Writes one ``{ "ts", "level", "event", "msg", ... }`` object per
  call, default sink is stderr.
- Auto-attaches the current trace/span ids when a tracer is bound
  (set via :meth:`StructuredLogger.bind_tracer`).
- Lets callers add ``with_context(...)`` extras (project root, user
  id, …) once and have them stamped on every subsequent record.

Non-blocking by design. If the sink raises we swallow the error so
logging never crashes the agent loop.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping

LogWriter = Callable[[str], None]


@dataclass(slots=True)
class LogRecord:
    """One emitted record. Open shape so it round-trips easily."""

    ts: float
    level: str
    event: str
    msg: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""
    span_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


def _default_writer(line: str) -> None:
    try:
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass


class StructuredLogger:
    """JSON-lines logger with tracer + context binding.

    Cheap to construct — pass one to every long-lived component or use
    :func:`get_default_logger` for the process-wide singleton.
    """

    def __init__(
        self,
        *,
        writer: LogWriter | None = None,
        level: str = "info",
        context: Mapping[str, Any] | None = None,
    ) -> None:
        self._writer: LogWriter = writer or _default_writer
        self._level = _normalise_level(level)
        self._context: dict[str, Any] = dict(context or {})
        self._tracer = None  # set via bind_tracer
        self._lock = threading.Lock()
        self._records: list[LogRecord] = []
        self._capture = False  # toggled by tests via :meth:`capture`

    # ------------------------------------------------------------------ binding

    def bind_tracer(self, tracer) -> None:
        """Attach a :class:`Tracer` so every record gets trace/span ids."""
        self._tracer = tracer

    def with_context(self, **extras: Any) -> "StructuredLogger":
        """Return a child logger with merged context."""
        ctx = dict(self._context)
        ctx.update(extras)
        child = StructuredLogger(writer=self._writer, level=_LEVEL_TO_NAME[self._level], context=ctx)
        child._tracer = self._tracer
        return child

    # ------------------------------------------------------------------ writes

    def log(self, level: str, event: str, msg: str = "", **data: Any) -> LogRecord:
        lvl = _normalise_level(level)
        record = LogRecord(
            ts=time.time(),
            level=_LEVEL_TO_NAME[lvl],
            event=event,
            msg=msg,
            data={**self._context, **data},
        )
        if self._tracer is not None:
            ctx = self._tracer.current_context()
            if ctx is not None:
                record.trace_id = ctx.trace_id
                record.span_id = ctx.span_id
        if lvl >= self._level:
            try:
                self._writer(record.to_json())
            except Exception:  # noqa: BLE001
                pass
        if self._capture:
            with self._lock:
                self._records.append(record)
        return record

    def debug(self, event: str, msg: str = "", **data: Any) -> LogRecord:
        return self.log("debug", event, msg, **data)

    def info(self, event: str, msg: str = "", **data: Any) -> LogRecord:
        return self.log("info", event, msg, **data)

    def warning(self, event: str, msg: str = "", **data: Any) -> LogRecord:
        return self.log("warning", event, msg, **data)

    def error(self, event: str, msg: str = "", **data: Any) -> LogRecord:
        return self.log("error", event, msg, **data)

    # ------------------------------------------------------------------ tools

    def capture(self, enabled: bool = True) -> None:
        """Turn on / off in-memory capture (tests & dashboards)."""
        with self._lock:
            self._capture = bool(enabled)
            if not enabled:
                self._records.clear()

    def captured(self) -> list[LogRecord]:
        with self._lock:
            return list(self._records)


# ----------------------------------------------------- helpers


_LEVELS: dict[str, int] = {
    "debug": 10,
    "info": 20,
    "warning": 30,
    "warn": 30,
    "error": 40,
    "fatal": 50,
}
_LEVEL_TO_NAME: dict[int, str] = {
    10: "debug",
    20: "info",
    30: "warning",
    40: "error",
    50: "fatal",
}


def _normalise_level(level: str | int) -> int:
    if isinstance(level, int):
        return int(level)
    return _LEVELS.get(str(level).strip().lower(), 20)


# ----------------------------------------------------- singleton


_DEFAULT: StructuredLogger | None = None
_DEFAULT_LOCK = threading.Lock()


def get_default_logger() -> StructuredLogger:
    """Lazy process-wide logger; respects ``VIBE_LOG_LEVEL`` env var."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = StructuredLogger(
                level=os.environ.get("VIBE_LOG_LEVEL", "info"),
            )
        return _DEFAULT


__all__ = ["LogRecord", "StructuredLogger", "get_default_logger"]
