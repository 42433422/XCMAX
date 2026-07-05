"""MODstore self-issued admin digest identity code."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, date, datetime, timedelta


def daily_digest_identity_code(day: str | None = None) -> str:
    d = (day or date.today().isoformat()).strip()
    secret = (os.environ.get("XCMAX_DIGEST_IDENTITY_SECRET") or "xcmax-local-digest-dev").strip()
    digest = hashlib.sha256(f"{secret}:{d}".encode()).hexdigest()
    return digest[:6].upper()


def verify_digest_identity_code(code: str, *, day: str | None = None) -> bool:
    c = (code or "").strip().upper()
    if len(c) != 6 or any(ch not in "0123456789ABCDEF" for ch in c):
        return False
    return c == daily_digest_identity_code(day)


def digest_identity_payload(*, digest_api_base: str = "") -> dict[str, object]:
    code = daily_digest_identity_code()
    expires = (datetime.now(UTC) + timedelta(hours=36)).isoformat()
    return {
        "success": True,
        "data": {
            "code": code,
            "expires_at": expires,
            "valid": True,
            "daily_digest_id": None,
            "digest_api_base": digest_api_base,
            "source": "modstore_self_issue",
        },
    }


__all__ = [
    "daily_digest_identity_code",
    "digest_identity_payload",
    "verify_digest_identity_code",
]
