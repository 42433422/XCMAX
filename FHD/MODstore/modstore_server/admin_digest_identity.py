"""管理端身份校验码 · 公网自签发（方案 A）。

与 FHD app/domain/admin_digest_identity.py 同算法。
"""
from __future__ import annotations

import hashlib
import os
from datetime import date, datetime, timedelta, timezone


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
    expires = (datetime.now(timezone.utc) + timedelta(hours=36)).isoformat()
    base = (digest_api_base or os.environ.get("MODSTORE_PUBLIC_API_BASE") or "").strip().rstrip("/")
    return {
        "success": True,
        "data": {
            "code": code,
            "expires_at": expires,
            "valid": True,
            "daily_digest_id": None,
            "digest_api_base": base,
            "source": "modstore_self_issue",
        },
    }
