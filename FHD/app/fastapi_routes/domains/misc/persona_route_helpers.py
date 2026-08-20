"""Request identity helpers for persona-backed Butler routes."""

from __future__ import annotations

from fastapi import Request


def resolve_persona_user_id(
    request: Request,
    body: dict | None = None,
    *,
    query_user_id: str | None = None,
) -> str:
    """Resolve the string user identity shared with web-normal chat sessions."""
    raw = (
        request.headers.get("X-User-Id")
        or request.headers.get("X-User-ID")
        or (body or {}).get("user_id")
        or (body or {}).get("userId")
        or query_user_id
        or "1"
    )
    return str(raw).strip() or "1"
