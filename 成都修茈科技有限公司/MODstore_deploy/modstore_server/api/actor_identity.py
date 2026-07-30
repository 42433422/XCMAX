"""Authenticated audit-actor identities for HTTP write paths."""

from __future__ import annotations

from typing import Any


def authenticated_admin_actor(user: Any) -> str:
    """Return a bounded identity derived only from the authenticated principal."""

    user_id = int(getattr(user, "id", 0) or 0)
    username = str(getattr(user, "username", "") or "").strip()
    return f"admin-user:{user_id}:{username or 'unknown'}"[:128]


__all__ = ["authenticated_admin_actor"]
