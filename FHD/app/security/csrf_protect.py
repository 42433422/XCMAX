"""CSRF token mint/verify for cookie-session browser surfaces."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets


def mint_csrf(secret: str | None = None) -> str:
    material = (
        secret or os.environ.get("CSRF_SECRET") or ""
    )  # credential-guard: allow — empty default; caller/tests pass secret
    nonce = secrets.token_urlsafe(16)
    sig = hmac.new(material.encode(), nonce.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{nonce}.{sig}"


def verify_csrf(token: str, secret: str | None = None) -> bool:
    if not token or "." not in token:
        return False
    nonce, sig = token.split(".", 1)
    material = (
        secret or os.environ.get("CSRF_SECRET") or ""
    )  # credential-guard: allow — empty default
    expect = hmac.new(material.encode(), nonce.encode(), hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(sig, expect)
