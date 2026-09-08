"""Authenticated principal used by the public Agent Run API."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
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
    mod_authorization: dict[str, Any] | None = None


def _bind_mod(
    request: Request, principal: AgentPrincipal, *, verified_session_id: str | None = None
) -> AgentPrincipal:
    from app.infrastructure.auth.agent_mod_scope import (
        AgentModAuthorizationError,
        bind_agent_mod_scope,
    )
    from app.infrastructure.auth.dependencies import session_id_from_request
    from app.request_active_mod_ctx import parse_active_mod_header

    mod_id = parse_active_mod_header(request.headers)
    if not mod_id:
        return principal
    try:
        binding = bind_agent_mod_scope(
            session_id=(verified_session_id if verified_session_id is not None
                        else session_id_from_request(request)),
            user_id=principal.user_id, mod_id=mod_id,
        )
    except AgentModAuthorizationError as exc:
        raise HTTPException(status_code=403, detail={"code": "MOD_NOT_ENTITLED", "message": str(exc)}) from exc
    return replace(principal, mod_authorization=binding)


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
        # The tutorial middleware is the only authority allowed to replace the
        # business tenant. Keep the authenticated user/role while making task
        # list, detail and commands observe the same shadow tenant as chat.
        if getattr(request.state, "tutorial_active", False) is True:
            tutorial_tenant = getattr(request.state, "tenant_id", None)
            if tutorial_tenant is not None:
                return _bind_mod(request, AgentPrincipal(
                    user_id=principal.user_id,
                    username=principal.username,
                    tenant_id=str(int(tutorial_tenant)),
                    is_admin=principal.is_admin,
                ))
        return _bind_mod(request, principal)

    authorization = request.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        payload = verify_mobile_jwt(authorization[7:].strip())
        if payload and payload.get("typ") == "access" and payload.get("user_id") is not None:
            return _bind_mod(request, AgentPrincipal(
                user_id=str(payload["user_id"]),
                username=str(payload.get("username") or ""),
                tenant_id=str(payload.get("tenant_id") or ""),
                is_admin=str(payload.get("account_kind") or "").lower() == "admin",
            ), verified_session_id=str(payload.get("session_id") or ""))

    # Explicitly test-only. Production cannot trust a caller-controlled identity header.
    if _test_header_enabled() and str(x_user_id or "").strip():
        return AgentPrincipal(user_id=str(x_user_id).strip())

    raise HTTPException(
        status_code=401,
        detail={"code": "UNAUTHORIZED", "message": "请先登录后使用 Agent"},
    )


__all__ = ["AgentPrincipal", "require_agent_principal"]
