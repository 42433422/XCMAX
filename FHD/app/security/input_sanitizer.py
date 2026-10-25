"""Input sanitization helpers for API and agent surfaces."""

from __future__ import annotations

import re
from typing import Any

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_SCRIPT = re.compile(r"<\s*script[^>]*>.*?<\s*/\s*script\s*>", re.I | re.S)


def strip_control_chars(value: str) -> str:
    return _CTRL.sub("", value)


def strip_script_tags(value: str) -> str:
    return _SCRIPT.sub("", value)


def sanitize_text(value: str, *, max_len: int = 10_000) -> str:
    text = strip_script_tags(strip_control_chars(value or ""))
    return text[:max_len]


def sanitize_mapping(data: dict[str, Any], *, max_len: int = 10_000) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in data.items():
        key = sanitize_text(str(k), max_len=128)
        if isinstance(v, str):
            out[key] = sanitize_text(v, max_len=max_len)
        elif isinstance(v, dict):
            out[key] = sanitize_mapping(v, max_len=max_len)
        else:
            out[key] = v
    return out
