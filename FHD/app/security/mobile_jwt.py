"""XCAGI Android 客户端 JWT（aud=xcagi-mobile，与小程序 JWT 区分）。

基于 PyJWT：强制 HS256 算法白名单、校验 iss/aud/exp；refresh token 一次性使用
（jti 黑名单，进程内内存 + 可选 Redis 跨副本共享）。
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

MOBILE_JWT_AUD = "xcagi-mobile"
MOBILE_JWT_ISS = "xcagi-mobile"
MOBILE_JWT_ALG = "HS256"
MOBILE_ACCESS_TTL_HOURS = 24
MOBILE_REFRESH_TTL_HOURS = 168

# 未配置 SECRET_KEY 时的进程级随机回退（不可预测），替代旧的硬编码
# ``xcagi-dev-secret``。生产应显式配置 SECRET_KEY；否则进程重启后历史 token
# 自然失效（安全优先，绝不使用可预测的固定默认值）。
_FALLBACK_SECRET = secrets.token_urlsafe(48)
_warned_missing_secret = False

# 已消费的 refresh token jti（一次性使用）；进程内内存 + 可选 Redis 跨副本共享。
_used_refresh_jti: set[str] = set()
_used_refresh_lock = threading.Lock()


def _secret_key() -> str:
    secret = os.environ.get("SECRET_KEY", "").strip()
    if secret:
        return secret
    global _warned_missing_secret
    if not _warned_missing_secret:
        logger.warning("SECRET_KEY 未配置，移动端 JWT 使用进程级随机密钥（重启后历史 token 失效）")
        _warned_missing_secret = True
    return _FALLBACK_SECRET


def _redis_blacklist():
    """可选 Redis 后端，用于跨副本共享已消费的 refresh jti；不可用时返回 None。"""
    try:
        from app.utils.redis_cache import get_redis_cache

        cache = get_redis_cache()
        return cache if getattr(cache, "is_available", False) else None
    except RECOVERABLE_ERRORS:
        return None


def _refresh_jti_seen(jti: str) -> bool:
    redis = _redis_blacklist()
    if redis is not None:
        try:
            if redis.get(f"mobile_refresh_used:{jti}"):
                return True
        except RECOVERABLE_ERRORS:
            pass
    with _used_refresh_lock:
        return jti in _used_refresh_jti


def _mark_refresh_jti_used(jti: str, ttl_seconds: int) -> None:
    redis = _redis_blacklist()
    if redis is not None:
        try:
            redis.set(f"mobile_refresh_used:{jti}", "1", ttl=ttl_seconds)
        except RECOVERABLE_ERRORS:
            pass
    with _used_refresh_lock:
        _used_refresh_jti.add(jti)


def verify_mobile_jwt(token: str) -> dict[str, Any] | None:
    """校验移动端 JWT：HS256 白名单 + iss/aud/exp 必校验。失败返回 None。"""
    try:
        return jwt.decode(
            token,
            _secret_key(),
            algorithms=[MOBILE_JWT_ALG],
            audience=MOBILE_JWT_AUD,
            issuer=MOBILE_JWT_ISS,
            options={"require": ["exp", "aud", "iss"]},
        )
    except jwt.PyJWTError as exc:
        logger.debug("mobile jwt verify failed: %s", exc)
        return None


def issue_mobile_tokens(
    *,
    user_id: int,
    session_id: str,
    account_kind: str = "enterprise",
    username: str = "",
) -> dict[str, str]:
    access = _issue_token(
        user_id=user_id,
        session_id=session_id,
        account_kind=account_kind,
        username=username,
        ttl_hours=MOBILE_ACCESS_TTL_HOURS,
        token_type="access",
    )
    refresh = _issue_token(
        user_id=user_id,
        session_id=session_id,
        account_kind=account_kind,
        username=username,
        ttl_hours=MOBILE_REFRESH_TTL_HOURS,
        token_type="refresh",
    )
    return {"access_token": access, "refresh_token": refresh}


def refresh_mobile_access_token(refresh_token: str) -> dict[str, str] | None:
    payload = verify_mobile_jwt(refresh_token)
    if not payload or payload.get("typ") != "refresh":
        return None
    jti = str(payload.get("jti") or "")
    # 一次性使用：缺 jti 或已被消费（重放）一律拒绝。
    if not jti or _refresh_jti_seen(jti):
        return None
    uid = payload.get("user_id")
    sid = payload.get("session_id")
    if uid is None or not sid:
        return None
    exp = int(payload.get("exp") or 0)
    ttl = max(1, exp - int(time.time())) if exp else MOBILE_REFRESH_TTL_HOURS * 3600
    _mark_refresh_jti_used(jti, ttl)
    return issue_mobile_tokens(
        user_id=int(uid),
        session_id=str(sid),
        account_kind=str(payload.get("account_kind") or "enterprise"),
        username=str(payload.get("username") or ""),
    )


def _issue_token(
    *,
    user_id: int,
    session_id: str,
    account_kind: str,
    username: str,
    ttl_hours: int,
    token_type: str,
) -> str:
    now = int(time.time())
    payload = {
        "aud": MOBILE_JWT_AUD,
        "iss": MOBILE_JWT_ISS,
        "typ": token_type,
        "user_id": user_id,
        "session_id": session_id,
        "account_kind": account_kind,
        "username": username,
        "iat": now,
        "exp": now + ttl_hours * 3600,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, _secret_key(), algorithm=MOBILE_JWT_ALG)


def user_id_from_mobile_bearer(authorization: str | None) -> int | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = verify_mobile_jwt(authorization[7:].strip())
    if not payload or payload.get("typ") != "access":
        return None
    uid = payload.get("user_id")
    return int(uid) if uid is not None else None
