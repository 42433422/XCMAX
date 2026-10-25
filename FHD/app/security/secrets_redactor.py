"""Redact secrets from logs and outbound payloads."""
from __future__ import annotations

import re
from typing import Any

_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization)\s*[:=]\s*(\S+)"),
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
]


def redact_text(text: str) -> str:
    out = text or ""
    for pat in _PATTERNS:
        out = pat.sub("[REDACTED]", out)
    return out


def redact_obj(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            k: ("[REDACTED]" if re.search(r"(?i)key|token|secret|password", str(k)) else redact_obj(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_obj(v) for v in value]
    return value
