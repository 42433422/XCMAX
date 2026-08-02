from __future__ import annotations

from typing import Any

_MAX_TRACE_STRING_CHARS = 4000
_MAX_TRACE_LIST_ITEMS = 20
_MAX_TRACE_DICT_ITEMS = 50


def trace_safe_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 4:
        return str(value)[:_MAX_TRACE_STRING_CHARS]
    if isinstance(value, str):
        if len(value) <= _MAX_TRACE_STRING_CHARS:
            return value
        return value[:_MAX_TRACE_STRING_CHARS] + "...[truncated]"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [trace_safe_value(item, depth=depth + 1) for item in value[:_MAX_TRACE_LIST_ITEMS]]
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for idx, (key, item) in enumerate(value.items()):
            if idx >= _MAX_TRACE_DICT_ITEMS:
                safe["_truncated"] = True
                break
            safe[str(key)] = trace_safe_value(item, depth=depth + 1)
        return safe
    return str(value)[:_MAX_TRACE_STRING_CHARS]
