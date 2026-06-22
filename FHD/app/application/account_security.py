"""账户安全：登录失败锁定 + MFA(TOTP, RFC 6238, 无第三方依赖)。

- 锁定：连续失败达阈值后锁定一段时间；成功登录清零。
- MFA：基于 ``User.totp_secret`` 的 TOTP 校验；标准认证器 App（Google/Microsoft Authenticator）兼容。
阈值可由环境变量覆盖：``XCAGI_MAX_LOGIN_ATTEMPTS``（默认 5）、``XCAGI_LOGIN_LOCKOUT_MINUTES``（默认 15）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time
from datetime import timedelta
from typing import Any

from app.utils.time import utc_now_naive


def _max_attempts() -> int:
    try:
        return max(1, int(os.environ.get("XCAGI_MAX_LOGIN_ATTEMPTS") or 5))
    except (TypeError, ValueError):
        return 5


def _lockout_minutes() -> int:
    try:
        return max(1, int(os.environ.get("XCAGI_LOGIN_LOCKOUT_MINUTES") or 15))
    except (TypeError, ValueError):
        return 15


# ── 账户锁定 ──────────────────────────────────────────────────────


def is_locked(user: Any) -> bool:
    lu = getattr(user, "locked_until", None)
    return lu is not None and lu > utc_now_naive()


def lock_remaining_seconds(user: Any) -> int:
    lu = getattr(user, "locked_until", None)
    if lu is None:
        return 0
    delta = (lu - utc_now_naive()).total_seconds()
    return int(delta) if delta > 0 else 0


def register_failed_attempt(user: Any) -> bool:
    """递增失败计数；达阈值则锁定。返回是否刚触发锁定。调用方负责 commit。"""
    attempts = int(getattr(user, "failed_login_attempts", 0) or 0) + 1
    if attempts >= _max_attempts():
        user.locked_until = utc_now_naive() + timedelta(minutes=_lockout_minutes())
        user.failed_login_attempts = 0
        return True
    user.failed_login_attempts = attempts
    return False


def reset_failed_attempts(user: Any) -> None:
    """成功登录后清零失败计数与锁定。调用方负责 commit。"""
    if getattr(user, "failed_login_attempts", 0):
        user.failed_login_attempts = 0
    if getattr(user, "locked_until", None) is not None:
        user.locked_until = None


# ── MFA / TOTP (RFC 6238) ─────────────────────────────────────────


def generate_totp_secret() -> str:
    """生成 base32 TOTP 密钥（认证器 App 录入用）。"""
    return base64.b32encode(os.urandom(20)).decode("ascii").rstrip("=")


def _hotp(secret_b32: str, counter: int, digits: int = 6) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % (10**digits)
    return str(code_int).zfill(digits)


def totp_now(secret_b32: str, *, step: int = 30, at: float | None = None) -> str:
    t = int(at if at is not None else time.time())
    return _hotp(secret_b32, t // step)


def verify_totp(
    secret_b32: str, code: str, *, step: int = 30, window: int = 1, at: float | None = None
) -> bool:
    """校验 TOTP；``window`` 允许前后各 N 个时间步容差（默认 ±1）。"""
    if not secret_b32 or not code:
        return False
    code = str(code).strip()
    if not code.isdigit():
        return False
    code = code.zfill(6)
    t = int(at if at is not None else time.time())
    counter = t // step
    for w in range(-window, window + 1):
        if hmac.compare_digest(_hotp(secret_b32, counter + w), code):
            return True
    return False


def provisioning_uri(secret_b32: str, account_name: str, issuer: str = "XCMAX") -> str:
    """otpauth:// URI（前端生成二维码供认证器扫码）。"""
    from urllib.parse import quote

    label = quote(f"{issuer}:{account_name}")
    return (
        f"otpauth://totp/{label}?secret={secret_b32}"
        f"&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"
    )


__all__ = [
    "generate_totp_secret",
    "is_locked",
    "lock_remaining_seconds",
    "provisioning_uri",
    "register_failed_attempt",
    "reset_failed_attempts",
    "totp_now",
    "verify_totp",
]
