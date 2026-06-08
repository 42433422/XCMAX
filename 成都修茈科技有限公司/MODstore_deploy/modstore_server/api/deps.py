"""Shared FastAPI dependencies for the HTTP layer."""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException

from modstore_server.application.auth import AuthApplicationService, AuthenticationError
from modstore_server.infrastructure.db import get_db
from modstore_server.models import User


def get_current_user(authorization: Optional[str] = Header(None)) -> User:
    try:
        return AuthApplicationService().current_user_from_authorization(authorization)
    except AuthenticationError as e:
        raise HTTPException(401, str(e)) from e


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    return user


# Legacy names used by existing modules while routers migrate into api/.
_get_current_user = get_current_user
_require_admin = require_admin

__all__ = ["_get_current_user", "_require_admin", "get_current_user", "get_db", "require_admin"]
