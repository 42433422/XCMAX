"""Auth helpers extracted for FastAPI deps."""

from __future__ import annotations

from typing import Optional

from fastapi import Header, HTTPException

from modstore_server.application.auth import AuthApplicationService, AuthenticationError
from modstore_server.auth_service import decode_access_token, get_user_by_id
from modstore_server.models import User, user_owns_mod

_auth = AuthApplicationService()


def get_optional_user(authorization: Optional[str] = Header(None)) -> Optional[User]:
    raw = (authorization or "").strip()
    if not raw.startswith("Bearer "):
        return None
    try:
        return _auth.current_user_from_authorization(authorization)
    except AuthenticationError:
        return None


def require_user(authorization: Optional[str] = Header(None)) -> User:
    try:
        return _auth.current_user_from_authorization(authorization)
    except AuthenticationError as e:
        raise HTTPException(401, str(e)) from e


def assert_user_owns_mod(user: User, mod_id: str) -> None:
    if not user.is_admin and not user_owns_mod(user.id, mod_id):
        raise HTTPException(403, "您无权访问此 MOD")
