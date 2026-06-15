"""CSRF token helpers (framework-agnostic)."""

from __future__ import annotations

import secrets

MUTATING_HTTP_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})
SAFE_HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def generate_csrf_token() -> str:
    return secrets.token_hex(32)


def csrf_tokens_match(header_token: str | None, cookie_token: str | None) -> bool:
    if not header_token or not cookie_token:
        return False
    return secrets.compare_digest(str(header_token).strip(), str(cookie_token).strip())
