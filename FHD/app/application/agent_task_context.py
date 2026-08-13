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
