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
    if not getattr(user, "is_active", True):
        return None
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


def bind_agent_runtime_context(
    context: dict[str, Any], principal: AgentPrincipal, *, run: Any = None
) -> dict[str, Any]:
    """Keep public task hints separate from host-established execution identity.

    Resume/approval preserves the task owner, including when an administrator
    controls another user's task. An account with no tenant cannot supply one.
    """
    protected = {
        "user_id",
        "userId",
        "local_user_id",
        "actor_id",
        "owner_id",
        "tenant_id",
        "service_source",
        "route_module",
        "route_confirmed",
        "is_admin",
        "role",
        "tier",
        "permissions",
        "permission_grants",
        "approved_by",
        "approved_step_id",
        "approval_grant",
        "headers",
        "cookies",
        "authorization",
    }
    safe = {
        key: value
        for key, value in context.items()
        if key not in protected and not key.startswith("_")
    }
    owner = str(run.user_id) if run is not None else principal.user_id
    saved = (run.metadata.get("runtime_context") or {}) if run is not None else {}
    tenant = str(saved.get("tenant_id") or "") if run is not None else principal.tenant_id
    safe.update(user_id=owner, local_user_id=owner, actor_id=owner, tenant_id=tenant)
    return safe


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
    if session_user is not None and not getattr(session_user, "is_active", True):
        raise HTTPException(
            status_code=403, detail={"code": "ACCOUNT_DISABLED", "message": "账户已被禁用"}
        )
    principal = _from_user(session_user) if session_user is not None else None
    if principal is not None:
        # The tutorial middleware is the only authority allowed to replace the
        # business tenant. Keep the authenticated user/role while making task
        # list, detail and commands observe the same shadow tenant as chat.
        if getattr(request.state, "tutorial_active", False) is True:
            tutorial_tenant = getattr(request.state, "tenant_id", None)
            if tutorial_tenant is not None:
                return AgentPrincipal(
                    user_id=principal.user_id,
                    username=principal.username,
                    tenant_id=str(int(tutorial_tenant)),
                    is_admin=principal.is_admin,
                )
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


__all__ = ["AgentPrincipal", "bind_agent_runtime_context", "require_agent_principal"]
