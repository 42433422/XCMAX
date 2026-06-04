"""TOTP 多因素认证（RFC 6238，stdlib 实现，无额外依赖）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time


def mfa_required_globally() -> bool:
    return os.environ.get("XCAGI_MFA_REQUIRED", "").strip().lower() in {"1", "true", "yes", "on"}


def generate_totp_secret() -> str:
    raw = os.urandom(20)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def _decode_secret(secret: str) -> bytes:
    padded = secret.upper().strip().replace(" ", "")
    pad = (-len(padded)) % 8
    return base64.b32decode(padded + ("=" * pad), casefold=True)


def totp_at(secret: str, *, for_time: int | None = None, period: int = 30, digits: int = 6) -> str:
    counter = int((for_time if for_time is not None else time.time()) // period)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(_decode_secret(secret), msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10**digits)).zfill(digits)


def verify_totp(secret: str, code: str, *, window: int = 1) -> bool:
    if not secret or not code:
        return False
    normalized = "".join(ch for ch in str(code) if ch.isdigit())
    if len(normalized) != 6:
        return False
    now = int(time.time())
    period = 30
    for drift in range(-window, window + 1):
        if hmac.compare_digest(totp_at(secret, for_time=now + drift * period), normalized):
            return True
    return False


def user_requires_mfa(*, mfa_enabled: bool | None, totp_secret: str | None) -> bool:
    if mfa_required_globally():
        return bool(totp_secret)
    return bool(mfa_enabled and totp_secret)
