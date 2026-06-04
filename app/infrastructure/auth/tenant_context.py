"""Resolve tenant context from HTTP headers (MVP multi-tenant RBAC)."""

from __future__ import annotations

from fastapi import Request

TENANT_HEADER = "X-Tenant-Id"


def resolve_tenant_id(request: Request) -> int | None:
    """Return numeric tenant id from ``X-Tenant-Id`` header, or None for platform scope."""
    raw = (request.headers.get(TENANT_HEADER) or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def resolve_tenant_code(request: Request) -> str | None:
    raw = (request.headers.get("X-Tenant-Code") or "").strip()
    return raw or None
