"""MODstore 用户认证服务：注册、登录、JWT。"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt

from modstore_server.models import User, Wallet, get_session_factory

_JWT_SECRET = os.environ.get("MODSTORE_JWT_SECRET", "modstore-dev-secret-change-in-prod")
_JWT_ALGORITHM = "HS256"
_JWT_EXPIRE_HOURS = 72


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: int, username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=_JWT_EXPIRE_HOURS)
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": expire,
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def register_user(username: str, password: str, email: str = "") -> User:
    sf = get_session_factory()
    with sf() as session:
        existing = session.query(User).filter(User.username == username).first()
        if existing:
            raise ValueError("用户名已存在")
        user = User(
            username=username,
            email=email or None,
            password_hash=hash_password(password),
        )
        session.add(user)
        session.flush()
        wallet = Wallet(user_id=user.id, balance=0.0)
        session.add(wallet)
        session.commit()
        session.refresh(user)
        return user


def authenticate_user(username: str, password: str) -> Optional[User]:
    sf = get_session_factory()
    with sf() as session:
        user = session.query(User).filter(User.username == username).first()
        if not user:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user


def get_user_by_id(user_id: int) -> Optional[User]:
    sf = get_session_factory()
    with sf() as session:
        return session.query(User).filter(User.id == user_id).first()
