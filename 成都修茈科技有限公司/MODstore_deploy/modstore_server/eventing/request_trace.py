"""W3C-ish trace context propagated from HTTP middleware into domain events."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Tuple

_trace_id: ContextVar[str] = ContextVar("modstore_trace_id", default="")
_span_id: ContextVar[str] = ContextVar("modstore_span_id", default="")


def set_trace_ids(trace_id: str, span_id: str = "") -> None:
    _trace_id.set((trace_id or "").strip()[:128])
    _span_id.set((span_id or "").strip()[:128])


def current_trace_ids() -> Tuple[str, str]:
    return _trace_id.get() or "", _span_id.get() or ""


__all__ = ["current_trace_ids", "set_trace_ids"]
