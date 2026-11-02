"""Pure execution policy predicates shared by the employee executor facade."""

from __future__ import annotations


def _flag_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_transient_llm_error(msg: str) -> bool:
    s = (msg or "").lower()
    if not s.strip():
        return False
    needles = (
        "timeout",
        "timed out",
        "connection reset",
        "connection aborted",
        "temporarily unavailable",
        "rate limit",
        "429",
        "503",
        "502",
        "bad gateway",
        "service unavailable",
        "eof occurred",
        "broken pipe",
        "connection refused",
        "connecterror",
        "readtimeout",
        "remotedisconnected",
        "try again",
        "overloaded",
    )
    return any((n in s for n in needles))
