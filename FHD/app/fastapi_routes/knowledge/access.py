"""Resolve knowledge access through the existing trusted HTTP principal owner."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

from app.application.dataset_rag.models import DatasetAccessContext
from app.utils.operational_errors import RECOVERABLE_ERRORS


def _request_tenant_key(request: Request | None) -> str | None:
    if request is None:
        return None
    try:
        from app.infrastructure.auth.dependencies import get_logged_in_user

        user = get_logged_in_user(request)
    except HTTPException:
        return None
    except RECOVERABLE_ERRORS:
        return None
    tenant_id = getattr(user, "tenant_id", None)
    if isinstance(tenant_id, bool) or not isinstance(tenant_id, int):
        return None
    return str(tenant_id)


def _dataset_access_context_from_request(request: Request) -> DatasetAccessContext | None:
    from app.fastapi_routes.dataset_access import dataset_access_context_from_request

    return dataset_access_context_from_request(request)


def _dataset_access_payload_from_request(request: Request) -> dict[str, Any]:
    from app.fastapi_routes.dataset_access import dataset_access_payload_from_request

    return dataset_access_payload_from_request(request)


def _dataset_read_tenant_scope(access: Any | None) -> str:
    """Tenant filter for per-dataset status/graph reads.

    Omniscient overview counts all tenants inside each dataset for admins. Per-dataset
    status/graph must use the same scope; otherwise admin console shows e.g. 1013 docs
    in the strip while the active space graph stays empty (filtered by admin's
    synthetic ``platform`` tenant).
    """
    if access is None:
        return ""
    if bool(getattr(access, "is_admin", False)):
        return ""
    permissions = getattr(access, "permissions", None) or ()
    try:
        from app.application.dataset_rag_app_service import DATASET_ADMIN_PERMISSION

        if DATASET_ADMIN_PERMISSION in permissions:
            return ""
    except RECOVERABLE_ERRORS:
        pass
    return str(getattr(access, "tenant_id", "") or "")
