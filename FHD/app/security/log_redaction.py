"""Redact sensitive patterns from log text before diagnostics export."""

from __future__ import annotations

import re

_BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)
_DB_URL = re.compile(
    r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s'\"<>]+",
    re.IGNORECASE,
)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----"
)
_AWS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_SK_KEY = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b")
_JSON_SECRET = re.compile(
    r'("(?:password|passwd|pwd|api[_-]?key|access[_-]?key|secret|token|refresh_token|access_token|database_url|connection_string|client_secret)"\s*:\s*")[^"]*"',
    re.IGNORECASE,
)
_API_KEY = re.compile(
    r"((?:api[_-]?key|x-api-key|access[_-]?key|secret[_-]?key|client[_-]?secret|authorization|password|passwd|pwd|secret|refresh_token|access_token|database_url|db_url|connection_string)\s*[:=]\s*)(\"?[^\s,;\"']+\"?)",
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
    out = _PRIVATE_KEY.sub("<redacted-private-key>", out)
    out = _DB_URL.sub("<redacted-database-url>", out)
    out = _BEARER.sub(r"\1<redacted>", out)
    out = _JWT.sub("<redacted-jwt>", out)
    out = _AWS_KEY.sub("<redacted>", out)
    out = _SK_KEY.sub("<redacted>", out)
    out = _JSON_SECRET.sub(r"\1<redacted>\"", out)
    out = _API_KEY.sub(r"\1<redacted>", out)
    out = _COOKIE.sub(r"\1<redacted>", out)
    out = _EMAIL.sub("<redacted-email>", out)
    out = _PHONE.sub("<redacted-phone>", out)
    return out


__all__ = ["redact_log_text"]
