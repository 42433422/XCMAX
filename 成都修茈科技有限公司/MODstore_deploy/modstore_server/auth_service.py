"""XC AGI 用户认证服务：注册、登录、JWT，以及 Personal Access Token (PAT) 工具。"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Tuple, cast

import bcrypt
import jwt
from sqlalchemy import func

from modstore_server.datetime_utils import as_utc_aware
from modstore_server.models import DeveloperToken, User, Wallet, get_session_factory

_JWT_ALGORITHM = "HS256"
_JWT_EXPIRE_HOURS = 72
_JWT_REFRESH_EXPIRE_DAYS = int(os.environ.get("MODSTORE_JWT_REFRESH_EXPIRE_DAYS", "3650"))


def _jwt_secret() -> str:
    secret = os.environ.get("MODSTORE_JWT_SECRET", "")
    if not secret:
        raise RuntimeError(
            "MODSTORE_JWT_SECRET 环境变量未设置。"
            '请设置一个强随机密钥（至少 32 字符），例如：python -c "import secrets; print(secrets.token_hex(32))"'
        )
    return secret


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    if hashed.startswith("$2b$") or hashed.startswith("$2a$") or hashed.startswith("$2y$"):
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    if hashed.startswith("pbkdf2:"):
        import base64 as _b64
        import hashlib as _hl

        try:
            parts = hashed.split("$")
            if len(parts) < 4:
                return False
            algo_part = parts[0]
            salt = parts[2]
            stored_hash = parts[3]
            iterations = int(algo_part.split(":")[-1])
            dk = _hl.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt.encode("utf-8"), iterations)
            computed = _b64.b64encode(dk).decode("utf-8")
            return computed == stored_hash
        except Exception:
            return False
    if hashed == "external-jwt":
        return False
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int, username: str, *, is_admin: bool = False) -> str:
    """签发 access JWT。``roles`` 与 Java 支付网关 ``JwtAuthenticationFilter`` 对齐（``ADMIN`` → ``ROLE_ADMIN``）。"""
    roles: List[str] = ["ADMIN"] if is_admin else []
    expire = datetime.now(timezone.utc) + timedelta(hours=_JWT_EXPIRE_HOURS)
    payload = {
        "sub": str(user_id),
        "username": username,
        "type": "access",
        "roles": roles,
        "exp": expire,
    }
    return cast(str, jwt.encode(payload, _jwt_secret(), algorithm=_JWT_ALGORITHM))


def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = cast(
            dict[Any, Any], jwt.decode(token, _jwt_secret(), algorithms=[_JWT_ALGORITHM])
        )
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
    # 兼容历史 token（无 type 字段）：默认按 access 处理；显式标 refresh 的不走这里。
    token_type = payload.get("type")
    if token_type and token_type != "access":
        return None
    return payload


def create_refresh_token(user_id: int, username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=_JWT_REFRESH_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "username": username,
        "type": "refresh",
        "exp": expire,
    }
    return cast(str, jwt.encode(payload, _jwt_secret(), algorithm=_JWT_ALGORITHM))


def decode_refresh_token(token: str) -> Optional[dict]:
    try:
        payload = cast(
            dict[Any, Any], jwt.decode(token, _jwt_secret(), algorithms=[_JWT_ALGORITHM])
        )
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
    if payload.get("type") != "refresh":
        return None
    return payload


def register_user(username: str, password: str, email: str = "") -> User:
    email_clean = (email or "").strip().lower() or ""
    sf = get_session_factory()
    with sf() as session:
        existing = session.query(User).filter(User.username == username).first()
        if existing:
            raise ValueError("用户名已存在")
        if email_clean:
            taken = session.query(User).filter(func.lower(User.email) == email_clean).first()
            if taken:
                raise ValueError("该邮箱已被注册")
        user = User(
            username=username,
            email=email_clean if email_clean else None,
            password_hash=hash_password(password),
        )
        session.add(user)
        session.flush()
        wallet = Wallet(user_id=user.id, balance=0.0)
        session.add(wallet)
        session.commit()
        session.refresh(user)
        session.expunge(user)
        return user


def authenticate_user(username: str, password: str) -> Optional[User]:
    sf = get_session_factory()
    with sf() as session:
        user = session.query(User).filter(User.username == username).first()
        if not user:
            return None
        if getattr(user, "deleted_at", None) is not None:
            return None
        if not verify_password(password, user.password_hash):
            return None
        session.expunge(user)
        return user


def get_user_by_id(user_id: int) -> Optional[User]:
    sf = get_session_factory()
    with sf() as session:
        user = session.query(User).filter(User.id == user_id).first()
        if user is not None:
            session.expunge(user)
        return user


def find_user_for_sso_identity(
    *,
    username: str = "",
    email: str = "",
    oidc_sub: str = "",
) -> Optional[User]:
    """按 SSO 声明查找市场用户（username 优先，其次 email）。"""
    _ = oidc_sub  # 预留 IdP sub 映射字段
    sf = get_session_factory()
    with sf() as session:
        uname = (username or "").strip()
        if uname:
            user = session.query(User).filter(User.username == uname).first()
            if user is not None and getattr(user, "deleted_at", None) is None:
                session.expunge(user)
                return user
        email_clean = (email or "").strip().lower()
        if email_clean:
            user = session.query(User).filter(func.lower(User.email) == email_clean).first()
            if user is not None and getattr(user, "deleted_at", None) is None:
                session.expunge(user)
                return user
    return None


def issue_market_tokens_for_sso_identity(
    *,
    username: str = "",
    email: str = "",
    oidc_sub: str = "",
    display_name: str = "",
    jit_provision: bool = True,
) -> dict[str, Any]:
    """FHD OIDC 回调经内部 API 换取 MODstore JWT；无用户时可 JIT 注册。"""
    user = find_user_for_sso_identity(username=username, email=email, oidc_sub=oidc_sub)
    if user is None and jit_provision:
        uname = (username or "").strip()
        if not uname and email:
            uname = email.split("@", 1)[0].strip()
        if not uname:
            raise ValueError("无法解析 SSO 用户名")
        pwd = secrets.token_urlsafe(32)
        user = register_user(uname, pwd, email or "")
        _ = display_name
    if user is None:
        raise ValueError("未找到对应的市场账号")
    is_admin = bool(getattr(user, "is_admin", False))
    access = create_access_token(user.id, user.username, is_admin=is_admin)
    refresh = create_refresh_token(user.id, user.username)
    return {
        "access_token": access,
        "token": access,
        "refresh_token": refresh,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": getattr(user, "email", None),
            "is_admin": is_admin,
            "is_enterprise": bool(getattr(user, "is_enterprise", False)),
        },
    }


# ----- Personal Access Token (PAT) -----------------------------------------

PAT_PREFIX = "pat_"
_PAT_BODY_LEN = 32  # base32hex 字符数；安全度 ≈ 160 bit


def hash_pat(raw_token: str) -> str:
    """sha256 反向哈希 (hex)，DB 端唯一索引。"""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_pat() -> Tuple[str, str, str]:
    """生成一个 PAT，返回 (raw_token, prefix, sha256_hex)。

    raw_token 仅一次性返回给客户端，prefix 用于 UI 掩码展示 (例：``pat_AbCdEf12``)。
    """
    body = secrets.token_urlsafe(_PAT_BODY_LEN)[:_PAT_BODY_LEN]
    raw = f"{PAT_PREFIX}{body}"
    prefix = raw[: len(PAT_PREFIX) + 8]
    return raw, prefix, hash_pat(raw)


@dataclass(frozen=True)
class PatIdentity:
    """Resolved PAT with scopes (used by machine / v1 sync routes)."""

    user: User
    scopes: tuple[str, ...]


def resolve_pat_identity(raw_token: str) -> Optional[PatIdentity]:
    """Resolve PAT to user + scopes; invalid / expired / revoked → ``None``."""

    raw = (raw_token or "").strip()
    if not raw.startswith(PAT_PREFIX):
        return None
    digest = hash_pat(raw)

    sf = get_session_factory()
    with sf() as session:
        row = (
            session.query(DeveloperToken)
            .filter(
                DeveloperToken.token_hash == digest,
                DeveloperToken.revoked_at.is_(None),
            )
            .first()
        )
        if not row:
            return None
        exp = as_utc_aware(row.expires_at)
        if exp and exp < datetime.now(timezone.utc):
            return None
        user = session.query(User).filter(User.id == row.user_id).first()
        if not user:
            return None
        try:
            scopes_raw = json.loads(row.scopes_json or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            scopes_raw = []
        if not isinstance(scopes_raw, list):
            scopes_raw = []
        scopes = tuple(str(s) for s in scopes_raw if s)
        try:
            row.last_used_at = datetime.now(timezone.utc)
            session.commit()
        except Exception:
            session.rollback()
        return PatIdentity(user=user, scopes=scopes)


def resolve_user_from_pat(raw_token: str) -> Optional[User]:
    """按 PAT 反查用户；非 ``pat_`` 前缀直接返回 None。

    命中后异步更新 ``last_used_at``。已吊销 / 已过期的 token 视为无效。
    """
    raw = (raw_token or "").strip()
    if not raw.startswith(PAT_PREFIX):
        return None
    digest = hash_pat(raw)

    sf = get_session_factory()
    with sf() as session:
        row = (
            session.query(DeveloperToken)
            .filter(
                DeveloperToken.token_hash == digest,
                DeveloperToken.revoked_at.is_(None),
            )
            .first()
        )
        if not row:
            return None
        exp = as_utc_aware(row.expires_at)
        if exp and exp < datetime.now(timezone.utc):
            return None
        user = session.query(User).filter(User.id == row.user_id).first()
        if not user:
            return None
        # 写一次 last_used_at（容忍并发竞态：单字段 UPDATE 安全）
        try:
            row.last_used_at = datetime.now(timezone.utc)
            session.commit()
        except Exception:
            session.rollback()
        return user
