"""Trusted identity helpers for durable task runtime context."""

from __future__ import annotations

from typing import Any

from app.infrastructure.tenant_scope import current_tenant_id


def attach_scoped_tenant(runtime_context: dict[str, Any]) -> None:
    """Copy only the already-authenticated request tenant into task context."""
    tenant_id = current_tenant_id()
    if tenant_id is not None:
        runtime_context["tenant_id"] = str(tenant_id)


def authenticated_task_owner(user_id: str, runtime_context: dict[str, Any]) -> str:
    """Prefer the authenticated local actor for durable task ownership."""
    return str(
        runtime_context.get("local_user_id") or runtime_context.get("actor_id") or user_id
    ).strip()


def scoped_conversation_user_id(user_id: str, context: dict[str, Any] | None) -> str:
    """Bind transient history and pending actions to the authenticated owner."""
    ctx = context or {}
    owner = ctx.get("local_user_id") or ctx.get("actor_id")
    if not owner:
        return user_id
    import hashlib
    import json

    scope = [
        str(ctx.get("tenant_id") or ""),
        str(owner),
        str(ctx.get("mod_id") or ctx.get("active_mod_id") or ""),
        str(ctx.get("session_id") or ctx.get("conversation_id") or user_id),
    ]
    return "chat:" + hashlib.sha256(json.dumps(scope, default=str).encode()).hexdigest()
