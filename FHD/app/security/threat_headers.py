"""Baseline security response headers."""

from __future__ import annotations

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "X-XSS-Protection": "0",
}


def apply_security_headers(headers: dict[str, str]) -> dict[str, str]:
    out = dict(headers)
    out.update(SECURITY_HEADERS)
    return out
