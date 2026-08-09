"""Authenticated principal used by the public Agent Run API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from fastapi import Header, HTTPException, Request

from app.infrastructure.auth.dependencies import resolve_session_user
from app.security.mobile_jwt import verify_mobile_jwt


@dataclass(frozen=True)
class AgentPrincipal:
    user_id: str
    username: str = ""
    tenant_id: str = ""
    is_admin: bool = False


def _from_user(user: Any) -> AgentPrincipal | None:
    user_id = getattr(user, "id", None)
    if user_id is None:
        return None
    tier = str(getattr(user, "tier", "") or "").strip().lower()
    role = str(getattr(user, "role", "") or "").strip().lower()
    return AgentPrincipal(
        user_id=str(user_id),
        username=str(getattr(user, "username", "") or ""),
        tenant_id=str(getattr(user, "tenant_id", "") or ""),
        is_admin=tier == "admin" or role == "admin",
    )


def _test_header_enabled() -> bool:
    return os.environ.get("FHD_ALLOW_X_USER_ID_HEADER", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def require_agent_principal(
    request: Request,
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
) -> AgentPrincipal:
    """Resolve a verified session/mobile JWT identity; reject anonymous callers."""
    session_user = resolve_session_user(request)
    principal = _from_user(session_user) if session_user is not None else None
    if principal is not None:
        return principal

    authorization = request.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        payload = verify_mobile_jwt(authorization[7:].strip())
        if payload and payload.get("typ") == "access" and payload.get("user_id") is not None:
            return AgentPrincipal(
                user_id=str(payload["user_id"]),
                username=str(payload.get("username") or ""),
                tenant_id=str(payload.get("tenant_id") or ""),
                is_admin=str(payload.get("account_kind") or "").lower() == "admin",
            )

    # Explicitly test-only. Production cannot trust a caller-controlled identity header.
    if _test_header_enabled() and str(x_user_id or "").strip():
        return AgentPrincipal(user_id=str(x_user_id).strip())

    raise HTTPException(
        status_code=401,
        detail={"code": "UNAUTHORIZED", "message": "请先登录后使用 Agent"},
    )


__all__ = ["AgentPrincipal", "require_agent_principal"]
