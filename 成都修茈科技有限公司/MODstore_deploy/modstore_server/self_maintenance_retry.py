"""Retry classification for self-maintenance employee dispatch failures."""

from __future__ import annotations

from typing import Any, Iterable

_FAILURE_TEXT_KEYS = frozenset(
    {"content", "detail", "error", "message", "reason", "status", "stderr", "stdout"}
)
_TRANSIENT_TERMS = (
    "client network socket disconnected before secure tls connection",
    "connection refused",
    "econnrefused",
    "econnreset",
    "para api 调用失败",
    "para_api_failed_outboxed",
    "para_api_rejected_outboxed",
    "report-only 执行器失败",
    "socket hang up",
    "ssl_error_syscall",
    "timeout waiting for para",
    "未在线",
)


def _failure_texts(value: Any, *, depth: int = 0) -> Iterable[str]:
    if depth > 6:
        return
    if isinstance(value, dict):
        for key, item in list(value.items())[:24]:
            if str(key).lower() in _FAILURE_TEXT_KEYS and isinstance(item, str):
                yield item
            if isinstance(item, (dict, list)):
                yield from _failure_texts(item, depth=depth + 1)
    elif isinstance(value, list):
        for item in value[:12]:
            yield from _failure_texts(item, depth=depth + 1)


def is_transient_dispatch_failure(result: Any) -> bool:
    """Recognize bounded-retry transport failures, including long CLI wrappers.

    Agent wrappers can echo a multi-kilobyte prompt before appending the real
    transport exception. Inspecting each failure field's tail preserves that
    root cause without scanning arbitrary successful report text.
    """

    for raw_text in _failure_texts(result):
        text = raw_text[-8000:].lower()
        if any(term in text for term in _TRANSIENT_TERMS):
            return True
    return False
