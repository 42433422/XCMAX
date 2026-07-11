"""Bounded, linear extraction of JSON objects from model output."""

from __future__ import annotations

import json
from typing import Any, Iterator

_FENCE = chr(96) * 3


def strip_json_fence(value: str) -> str:
    """Remove one complete Markdown JSON fence without a backtracking regex."""

    text = str(value or "").strip()
    if not text.startswith(_FENCE):
        return text
    newline = text.find("\n")
    if newline < 0:
        return text
    opener = text[:newline].strip().lower()
    if opener not in {_FENCE, _FENCE + "json"}:
        return text
    body = text[newline + 1 :].rstrip()
    if not body.endswith(_FENCE):
        return text
    return body[: -len(_FENCE)].strip()


def _balanced_objects(value: str) -> Iterator[str]:
    """Yield disjoint balanced JSON object candidates in a single pass."""

    start = -1
    depth = 0
    quoted = False
    escaped = False
    for index, char in enumerate(value):
        if start < 0:
            if char == "{":
                start = index
                depth = 1
                quoted = False
                escaped = False
            continue
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                yield value[start : index + 1]
                start = -1


def parse_json_object(value: Any, *, required_key: str = "") -> dict[str, Any]:
    """Parse a JSON object from plain, fenced, or prose-wrapped model output."""

    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    text = value.strip()
    candidates = [text]
    unfenced = strip_json_fence(text)
    if unfenced != text:
        candidates.append(unfenced)
    candidates.extend(_balanced_objects(unfenced))
    fallback: dict[str, Any] = {}
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(parsed, dict):
            continue
        if not fallback:
            fallback = parsed
        if not required_key or required_key in parsed:
            return parsed
    return fallback if not required_key else {}


__all__ = ["parse_json_object", "strip_json_fence"]
