"""XCAGI Android 客户端 JWT（aud=xcagi-mobile，与小程序 JWT 区分）。

基于 PyJWT：强制 HS256 算法白名单、校验 iss/aud/exp；refresh token 一次性使用
（jti 黑名单，进程内内存 + 可选 Redis 跨副本共享）。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any

import jwt

from app.security.jwt_signing_key import resolve_jwt_signing_key
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

MOBILE_JWT_AUD = "xcagi-mobile"
MOBILE_JWT_ISS = "xcagi-mobile"
MOBILE_JWT_ALG = "HS256"
MOBILE_ACCESS_TTL_HOURS = 24
MOBILE_REFRESH_TTL_HOURS = 168

# 已消费的 refresh token jti（一次性使用）；进程内内存 + 可选 Redis 跨副本共享。
_used_refresh_jti: set[str] = set()
_used_refresh_lock = threading.Lock()


def _secret_key() -> str:
    """稳定签名密钥：环境变量优先，未配置时使用持久化实例密钥（跨重启有效）。"""
    return resolve_jwt_signing_key()


def _mobile_session_is_live(session_id: str) -> bool:
    """refresh 前校验底层会话仍然有效，避免给已失效会话续签 token。

    relay 会话是配对时生成的轻量会话，不落 sessions 表，直接放行。
    数据库瞬时不可用时按「未知」处理并允许续签（token 本身仍验签通过），
    避免把一次基础设施抖动误判为登出。
    """
    sid = session_id.strip()
    if not sid:
        return False
    if sid.startswith("mobile-relay-"):
        return True
    try:
        from app.application.facades.session_facade import get_session_service

        return get_session_service().get_session_info(sid) is not None
    except RECOVERABLE_ERRORS as exc:
        logger.warning("mobile refresh session check unavailable: %s", exc)
        return True


def _redis_blacklist():
    """可选 Redis 后端，用于跨副本共享已消费的 refresh jti；不可用时返回 None。"""
    try:
        from app.utils.performance.redis_cache import get_redis_cache

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
    from app.infrastructure.auth.mobile_session import ADMIN_ACCOUNT_KINDS, current_mobile_admin

    account_kind = str(payload.get("account_kind") or "").strip().lower()
    if account_kind in ADMIN_ACCOUNT_KINDS:
        # 管理端仍走市场管理员会话校验（main 的既有语义）。
        if current_mobile_admin(uid, sid) is None:
            return None
    elif not _mobile_session_is_live(str(sid)):
        # 普通/企业会话已删除或过期时拒绝续签：否则客户端会拿到新 token
        # 却仍在 session 相关接口收到 401，形成「refresh 成功 + 业务 401」循环。
        logger.info("mobile refresh rejected: session %s is no longer valid", sid)
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
