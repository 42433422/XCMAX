"""Input sanitization helpers for API and agent surfaces."""

from __future__ import annotations

import re
from typing import Any

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
# End tag must allow whitespace/attrs before '>' (e.g. </script\t\n bar>).
# See CodeQL py/bad-tag-filter (alert #3918).
_SCRIPT_PAIR = re.compile(
    r"<\s*script\b[^>]*>.*?<\s*/\s*script[^>]*>",
    re.IGNORECASE | re.DOTALL,
)
_SCRIPT_ORPHAN = re.compile(r"<\s*/?\s*script\b[^>]*>", re.IGNORECASE)


def strip_control_chars(value: str) -> str:
    return _CTRL.sub("", value)


def strip_script_tags(value: str) -> str:
    text = value or ""
    prev = None
    while prev != text:
        prev = text
        text = _SCRIPT_PAIR.sub("", text)
    return _SCRIPT_ORPHAN.sub("", text)


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
