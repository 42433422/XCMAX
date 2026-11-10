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


def scoped_personal_memory_id(context: dict[str, Any] | None) -> str:
    """Return an authenticated owner's cross-session memory namespace.

    Conversation history and pending workflows stay session-scoped. Recallable
    personal memory survives a new conversation, while tenant and Mod boundaries
    keep one user's memory isolated across product scopes.
    """
    import hashlib
    import json

    from app.application.task_conversation_store import durable_user_id

    ctx = context or {}
    owner = durable_user_id(ctx.get("local_user_id") or ctx.get("actor_id"))
    if owner is None:
        return ""
    scope = [
        str(ctx.get("tenant_id") or ""),
        str(owner),
        str(ctx.get("mod_id") or ctx.get("active_mod_id") or ""),
    ]
    return "personal-memory:v1:" + hashlib.sha256(
        json.dumps(scope, ensure_ascii=False).encode()
    ).hexdigest()
