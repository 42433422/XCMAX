"""Knowledge v1 access/tenant helpers (extracted for source-governance)."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

_PUBLIC_KNOWLEDGE_TENANT_ID = "public"


def _dataset_access_context_from_request(request: Request) -> Any | None:
    from app.fastapi_routes.dataset_access import dataset_access_context_from_request

    return dataset_access_context_from_request(request)


def _dataset_read_tenant_scope(access: Any | None) -> str:
    """Tenant filter for per-dataset status/graph reads.

    Omniscient overview counts all tenants inside each dataset for admins. Per-dataset
    status/graph must use the same scope; otherwise admin console shows e.g. 1013 docs
    in the strip while the active space graph stays empty (filtered by admin's
    synthetic ``platform`` tenant).
    """

    if access is None:
        return _PUBLIC_KNOWLEDGE_TENANT_ID
    if bool(getattr(access, "is_admin", False)):
        return ""
    permissions = getattr(access, "permissions", None) or ()
    try:
        from app.application.dataset_rag_app_service import DATASET_ADMIN_PERMISSION

        if DATASET_ADMIN_PERMISSION in permissions:
            return ""
    except (ImportError, TypeError, AttributeError):
        pass
    return str(getattr(access, "tenant_id", "") or "")


def _dataset_admin_access(access: Any | None) -> bool:
    if access is None:
        return False
    if bool(getattr(access, "is_admin", False)):
        return True
    permissions = getattr(access, "permissions", None) or ()
    return "dataset.admin" in permissions or "*" in permissions


def _private_scope_requires_auth(tenant_id: str, access: Any | None) -> JSONResponse | None:
    requested = str(tenant_id or "").strip()
    if access is not None or not requested or requested == _PUBLIC_KNOWLEDGE_TENANT_ID:
        return None
    return JSONResponse(
        {
            "success": False,
            "error_code": "dataset_auth_required",
            "message": "企业私有知识需要登录后访问",
        },
        status_code=401,
    )
