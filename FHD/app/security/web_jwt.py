"""Web 端无状态 JWT（aud=xcagi-web），与有状态 session 并存的增量能力。

设计（非破坏）：
- 登录成功时附带签发 web access/refresh token（前端/API 客户端可选用）。
- ``resolve_session_user`` 仅在 ``XCAGI_WEB_JWT_AUTH=1`` 时、且 session 校验失败后，
  才尝试用 web JWT 验签加载用户（默认关 → 现有有状态 session 行为零变化）。
- refresh token 一次性轮转（jti 进程内黑名单）。
- 与 mobile_jwt 一致：PyJWT + HS256 白名单 + iss/aud/exp 强校验 + SECRET_KEY。

启用无状态 JWT 认证为正式切换点：需前端改用 Bearer JWT 并接 /api/auth/token/refresh。
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
import uuid
from typing import Any

import jwt

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

WEB_JWT_AUD = "xcagi-web"
WEB_JWT_ISS = "xcagi-web"
WEB_JWT_ALG = "HS256"
WEB_ACCESS_TTL_HOURS = 12
WEB_REFRESH_TTL_HOURS = 336  # 14 天

_FALLBACK_SECRET = secrets.token_urlsafe(48)
_used_refresh_jti: set[str] = set()
_used_refresh_lock = threading.Lock()


def _secret_key() -> str:
    return os.environ.get("SECRET_KEY", "").strip() or _FALLBACK_SECRET


def web_jwt_auth_enabled() -> bool:
    """是否启用「用 web JWT 认证」（默认关；开启即正式无状态化切换点）。"""
    return (os.environ.get("XCAGI_WEB_JWT_AUTH") or "").strip().lower() in ("1", "true", "yes")


def _issue(*, user_id: int, username: str, account_kind: str, ttl_hours: int, typ: str) -> str:
    now = int(time.time())
    payload = {
        "aud": WEB_JWT_AUD,
        "iss": WEB_JWT_ISS,
        "typ": typ,
        "user_id": int(user_id),
        "username": username,
        "account_kind": account_kind,
        "iat": now,
        "exp": now + ttl_hours * 3600,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, _secret_key(), algorithm=WEB_JWT_ALG)


def issue_web_tokens(
    *, user_id: int, username: str = "", account_kind: str = "enterprise"
) -> dict[str, str]:
    return {
        "access_token": _issue(
            user_id=user_id,
            username=username,
            account_kind=account_kind,
            ttl_hours=WEB_ACCESS_TTL_HOURS,
            typ="access",
        ),
        "refresh_token": _issue(
            user_id=user_id,
            username=username,
            account_kind=account_kind,
            ttl_hours=WEB_REFRESH_TTL_HOURS,
            typ="refresh",
        ),
    }


def verify_web_jwt(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(
            token,
            _secret_key(),
            algorithms=[WEB_JWT_ALG],
            audience=WEB_JWT_AUD,
            issuer=WEB_JWT_ISS,
            options={"require": ["exp", "aud", "iss"]},
        )
    except jwt.PyJWTError as exc:
        logger.debug("web jwt verify failed: %s", exc)
        return None


def refresh_web_access_token(refresh_token: str) -> dict[str, str] | None:
    """校验 refresh token 并轮转出新的 access/refresh（一次性使用）。"""
    payload = verify_web_jwt(refresh_token)
    if not payload or payload.get("typ") != "refresh":
        return None
    jti = str(payload.get("jti") or "")
    with _used_refresh_lock:
        if jti and jti in _used_refresh_jti:
            return None
        if jti:
            _used_refresh_jti.add(jti)
    return issue_web_tokens(
        user_id=int(payload["user_id"]),
        username=str(payload.get("username") or ""),
        account_kind=str(payload.get("account_kind") or "enterprise"),
    )


def resolve_user_from_web_jwt(token: str) -> Any | None:
    """验签 web access JWT 并按 user_id 加载 User（无状态：不查 sessions 表）。

    仅在 ``XCAGI_WEB_JWT_AUTH=1`` 时生效；否则返回 None（保持有状态 session 行为）。
    """
    if not web_jwt_auth_enabled():
        return None
    payload = verify_web_jwt(token)
    if not payload or payload.get("typ") != "access":
        return None
    uid = payload.get("user_id")
    if uid is None:
        return None
    try:
        from app.db.models.user import User
        from app.db.session import get_db

        with get_db() as db:
            user = db.get(User, int(uid))
            if user is None or not getattr(user, "is_active", True):
                return None
            # 触发常用列加载后 detach，供会话关闭后按标量属性使用
            _ = (user.id, user.tier, user.industry_id, user.tenant_id, user.role)
            db.expunge(user)
            return user
    except RECOVERABLE_ERRORS:
        logger.debug("resolve_user_from_web_jwt failed", exc_info=True)
        return None


__all__ = [
    "issue_web_tokens",
    "refresh_web_access_token",
    "resolve_user_from_web_jwt",
    "verify_web_jwt",
    "web_jwt_auth_enabled",
]
