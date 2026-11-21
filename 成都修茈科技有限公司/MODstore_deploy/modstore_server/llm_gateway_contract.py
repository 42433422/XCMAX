"""Thin controls for metered calls through the existing LiteLLM proxy.

The local Router's retry settings do not constrain a second proxy hop. These
controls belong to the trusted transport, and the receipt must come from the
native HTTP response headers before any local Router normalization.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def gateway_body(provider: str) -> dict[str, Any]:
    """Return server-owned per-request proxy controls, never worker input."""
    return {"num_retries": 0, "disable_fallbacks": True} if provider == "litellm" else {}


def gateway_single_attempt(headers: Mapping[str, object]) -> bool:
    """Require both native proxy counters to prove no hidden paid attempts.

    Missing, duplicated, malformed, or positive counters are unknown usage, not
    evidence of zero retries. A response's final usage alone cannot settle it.
    """
    for name in ("x-litellm-attempted-retries", "x-litellm-attempted-fallbacks"):
        values = [value for key, value in headers.items() if key.lower() == name]
        if len(values) != 1:
            return False
        value = values[0]
        if type(value) is int and value == 0:
            continue
        if not isinstance(value, str):
            return False
        value = value.strip()
        if not value or not value.isascii() or not value.isdecimal():
            return False
        if any(character != "0" for character in value):
            return False
    return True
