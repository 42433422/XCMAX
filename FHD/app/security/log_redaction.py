"""Redact sensitive patterns from log text before diagnostics export."""

from __future__ import annotations

import re

_BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)
_API_KEY = re.compile(
    r"((?:api[_-]?key|x-api-key|authorization)\s*[:=]\s*)[^\s,;\"']+",
    re.IGNORECASE,
)
_COOKIE = re.compile(
    r"((?:session_id|cookie)\s*[:=]\s*)[^\s,;\"']+",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"\b1[3-9]\d{9}\b")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")


def redact_log_text(text: str) -> str:
    """Return log text with common secret / PII patterns masked."""
    if not text:
        return text
    out = text
    out = _BEARER.sub(r"\1<redacted>", out)
    out = _JWT.sub("<redacted-jwt>", out)
    out = _API_KEY.sub(r"\1<redacted>", out)
    out = _COOKIE.sub(r"\1<redacted>", out)
    out = _EMAIL.sub("<redacted-email>", out)
    out = _PHONE.sub("<redacted-phone>", out)
    return out


__all__ = ["redact_log_text"]
