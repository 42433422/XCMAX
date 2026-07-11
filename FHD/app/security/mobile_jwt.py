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
MOBILE_RELAY_TOKEN_SCOPES = frozenset({"enterprise_pairing", "enterprise_relay"})
MOBILE_MANAGEMENT_PAIRING_SCOPE = "management_pairing"

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
        payload = jwt.decode(
            token,
            _secret_key(),
            algorithms=[MOBILE_JWT_ALG],
            audience=MOBILE_JWT_AUD,
            issuer=MOBILE_JWT_ISS,
            options={"require": ["exp", "aud", "iss"]},
        )
        if not _relay_token_is_current(payload):
            logger.info("legacy or privileged mobile relay token rejected")
            return None
        return payload
    except jwt.PyJWTError as exc:
        logger.debug("mobile jwt verify failed: %s", exc)
        return None


def _relay_token_is_current(payload: dict[str, Any]) -> bool:
    """Fail closed for pre-upgrade LAN credentials.

    Older pairing flows minted an administrator JWT with a ``mobile-relay-*``
    session and no explicit scope.  Those credentials must stop working as soon
    as the upgraded backend starts, rather than retaining management access until
    their natural expiry.  Current relay credentials are always enterprise-only
    and bound to an exact DB user, tenant namespace and issuer.
    """
    session_id = str(payload.get("session_id") or "").strip()
    if session_id.startswith("mobile-management-"):
        scope = str(payload.get("token_scope") or "").strip()
        account_kind = str(payload.get("account_kind") or "").strip().lower()
        try:
            user_id = int(payload.get("user_id") or 0)
            paired_by_user_id = int(payload.get("paired_by_user_id") or 0)
        except (TypeError, ValueError):
            return False
        return (
            scope == MOBILE_MANAGEMENT_PAIRING_SCOPE
            and account_kind in {"admin", "admin_portal"}
            and user_id > 0
            and paired_by_user_id == user_id
            and "tenant_id" in payload
            and bool(str(payload.get("company_brand") or "").strip())
        )
    if not session_id.startswith("mobile-relay-"):
        return True
    scope = str(payload.get("token_scope") or "").strip()
    account_kind = str(payload.get("account_kind") or "").strip().lower()
    try:
        user_id = int(payload.get("user_id") or 0)
        paired_by_user_id = int(payload.get("paired_by_user_id") or 0)
    except (TypeError, ValueError):
        return False
    return (
        scope in MOBILE_RELAY_TOKEN_SCOPES
        and account_kind == "enterprise"
        and user_id > 0
        and paired_by_user_id == user_id
        and "tenant_id" in payload
        and bool(str(payload.get("company_brand") or "").strip())
    )


def issue_mobile_tokens(
    *,
    user_id: int,
    session_id: str,
    account_kind: str = "enterprise",
    username: str = "",
    token_scope: str = "",
    tenant_id: int | None = None,
    company_brand: str = "",
    paired_by_user_id: int | None = None,
) -> dict[str, str]:
    access = _issue_token(
        user_id=user_id,
        session_id=session_id,
        account_kind=account_kind,
        username=username,
        token_scope=token_scope,
        tenant_id=tenant_id,
        company_brand=company_brand,
        paired_by_user_id=paired_by_user_id,
        ttl_hours=MOBILE_ACCESS_TTL_HOURS,
        token_type="access",
    )
    refresh = _issue_token(
        user_id=user_id,
        session_id=session_id,
        account_kind=account_kind,
        username=username,
        token_scope=token_scope,
        tenant_id=tenant_id,
        company_brand=company_brand,
        paired_by_user_id=paired_by_user_id,
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
        token_scope=str(payload.get("token_scope") or ""),
        tenant_id=_optional_int(payload.get("tenant_id")),
        company_brand=str(payload.get("company_brand") or ""),
        paired_by_user_id=_optional_int(payload.get("paired_by_user_id")),
    )


def _issue_token(
    *,
    user_id: int,
    session_id: str,
    account_kind: str,
    username: str,
    token_scope: str,
    tenant_id: int | None,
    company_brand: str,
    paired_by_user_id: int | None,
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
    if token_scope.strip():
        payload["token_scope"] = token_scope.strip()[:64]
    if tenant_id is not None:
        payload["tenant_id"] = int(tenant_id)
    if company_brand.strip():
        payload["company_brand"] = company_brand.strip()[:256]
    if paired_by_user_id is not None:
        payload["paired_by_user_id"] = int(paired_by_user_id)
    return jwt.encode(payload, _secret_key(), algorithm=MOBILE_JWT_ALG)


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def user_id_from_mobile_bearer(authorization: str | None) -> int | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = verify_mobile_jwt(authorization[7:].strip())
    if not payload or payload.get("typ") != "access":
        return None
    uid = payload.get("user_id")
    return int(uid) if uid is not None else None
