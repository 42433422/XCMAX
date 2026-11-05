"""Optional web JWT authentication with durable, atomic refresh-token consumption.

The shared host database, not a process-local set, is authoritative for refresh
replay prevention. Deploy the additive replay-table migration before enabling
JWT authentication. Database errors fail closed; there is no memory fallback.
Legacy refresh tokens require a new login: their consumed identities cannot be
recovered from old process memory. Drain all old refresh workers at cutover;
mixed deployments or rollback to the memory implementation are not replay-safe.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
import uuid
from typing import Any

import jwt
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
WEB_JWT_AUD = "xcagi-web"
WEB_JWT_ISS = "xcagi-web"
WEB_JWT_ALG = "HS256"
WEB_ACCESS_TTL_HOURS = 12
WEB_REFRESH_TTL_HOURS = 336
_REFRESH_PROTOCOL = "durable-v1"
_FALLBACK_SECRET = secrets.token_urlsafe(48)


def web_jwt_auth_enabled() -> bool:
    return (os.environ.get("XCAGI_WEB_JWT_AUTH") or "").strip().lower() in ("1", "true", "yes")


def _secret_key() -> str:
    configured = os.environ.get("SECRET_KEY", "").strip()
    if not configured and web_jwt_auth_enabled():
        raise RuntimeError("SECRET_KEY is required when XCAGI_WEB_JWT_AUTH is enabled")
    return configured or _FALLBACK_SECRET


def _issue(
    *,
    user_id: int,
    username: str,
    account_kind: str,
    ttl_hours: int,
    typ: str,
    session_id: str = "",
) -> str:
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
    if typ == "refresh":
        payload["refresh_protocol"] = _REFRESH_PROTOCOL
    if session_id:
        payload["session_id"] = session_id
    return jwt.encode(payload, _secret_key(), algorithm=WEB_JWT_ALG)


def issue_web_tokens(
    *, user_id: int, username: str = "", account_kind: str = "enterprise", session_id: str = ""
) -> dict[str, str]:
    return {
        "access_token": _issue(
            user_id=user_id,
            username=username,
            account_kind=account_kind,
            session_id=session_id,
            ttl_hours=WEB_ACCESS_TTL_HOURS,
            typ="access",
        ),
        "refresh_token": _issue(
            user_id=user_id,
            username=username,
            account_kind=account_kind,
            session_id=session_id,
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
            options={"require": ["exp", "aud", "iss", "jti", "user_id", "typ"]},
        )
    except (jwt.PyJWTError, RuntimeError) as exc:
        logger.debug("web jwt verify failed: %s", exc)
        return None


def _consume_refresh_jti(db: Any, jti: str, expires_at: int, now: int) -> bool:
    """Caller must commit before releasing replacement tokens to the client."""
    if (
        not isinstance(jti, str)
        or not jti
        or len(jti) > 64
        or type(expires_at) is not int
        or not now < expires_at <= 2**63 - 1
    ):
        return False
    # Expired tokens have already been rejected cryptographically. Indexed cleanup
    # keeps the store bounded by valid token lifetime without enabling valid replay.
    db.execute(text("DELETE FROM web_refresh_token_uses WHERE expires_at < :now"), {"now": now})
    try:
        with db.begin_nested():
            db.execute(
                text(
                    "INSERT INTO web_refresh_token_uses (jti, expires_at) "
                    "VALUES (:jti, :expires_at)"
                ),
                {"jti": jti, "expires_at": expires_at},
            )
        return True
    except IntegrityError:
        return False


def refresh_web_access_token(refresh_token: str) -> dict[str, str] | None:
    payload = verify_web_jwt(refresh_token)
    if (
        not payload
        or payload.get("typ") != "refresh"
        or payload.get("refresh_protocol") != _REFRESH_PROTOCOL
    ):
        return None
    jti, expires_at, user_id = payload.get("jti"), payload.get("exp"), payload.get("user_id")
    if (
        not isinstance(jti, str)
        or not jti
        or len(jti) > 64
        or type(expires_at) is not int
        or type(user_id) is not int
        or user_id <= 0
    ):
        return None
    try:
        # Generate before consuming so signing/configuration errors do not burn the
        # refresh token. The result remains private until the DB commit succeeds.
        rotated = issue_web_tokens(
            user_id=user_id,
            username=str(payload.get("username") or ""),
            account_kind=str(payload.get("account_kind") or "enterprise"),
            session_id=str(payload.get("session_id") or ""),
        )
        from app.db.session import get_host_db

        with get_host_db() as db:
            consumed = _consume_refresh_jti(db, jti, expires_at, int(time.time()))
        return rotated if consumed else None
    except (SQLAlchemyError, RuntimeError):
        logger.warning("web JWT refresh unavailable; refusing rotation", exc_info=True)
        return None


def resolve_user_from_web_jwt(token: str) -> Any | None:
    if not web_jwt_auth_enabled():
        return None
    payload = verify_web_jwt(token)
    if not payload or payload.get("typ") != "access":
        return None
    uid = payload.get("user_id")
    if type(uid) is not int or uid <= 0:
        return None
    try:
        from app.db.models.user import User
        from app.db.session import get_host_db

        with get_host_db() as db:
            user = db.get(User, uid)
            if user is None or not getattr(user, "is_active", True):
                return None
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
