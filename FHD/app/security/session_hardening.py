"""Session cookie hardening defaults."""

from __future__ import annotations

from typing import Any


def hardened_cookie_params(*, secure: bool = True) -> dict[str, Any]:
    return {
        "httponly": True,
        "secure": secure,
        "samesite": "lax",
        "max_age": 60 * 60 * 12,
    }
