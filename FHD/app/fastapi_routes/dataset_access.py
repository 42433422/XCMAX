"""Trusted dataset access context derived at the HTTP boundary."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

from app.application.dataset_rag_app_service import (
    DATASET_READ_PERMISSION,
    DATASET_WRITE_PERMISSION,
    DatasetAccessContext,
)
from app.infrastructure.auth.dependencies import get_logged_in_user, resolve_session_user
from app.infrastructure.auth.tenant_context import resolve_tenant_id
from app.mod_sdk.product_skus import resolve_product_sku
from app.utils.deployment import (
    deployment_is_test,
    env_flag,
    is_desktop_mode,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

_CLIENT_ACCESS_KEYS = frozenset(
    {
        "_dataset_access_context",
        "_dataset_access_context_trusted",
        "dataset_access_context",
        "dataset_access_trusted",
        "dataset_permissions",
        "dataset_admin",
        "dataset_tenant_id",
    }
)


def dataset_access_context_from_request(
    request: Request,
    *,
    allow_local_default_read: bool = False,
) -> DatasetAccessContext | None:
    """Resolve a dataset principal from session first, then trusted gateway headers.

    Header compatibility remains for the existing gateway and route contract.
    The resulting object only becomes trusted after this server-side function.
    """

    user = resolve_session_user(request)
    if user is not None:
        if not getattr(user, "is_active", True):
            return DatasetAccessContext()
        actor_id = str(getattr(user, "id", "") or "")
        tenant = str(getattr(user, "tenant_id", "") or "")
        role = str(getattr(user, "role", "") or "").strip().lower()
        is_admin = (
            role in {"admin", "super_admin"}
            and getattr(user, "tier", None) == "admin"
            and getattr(user, "tenant_id", None) is None
        )
        permissions: set[str] = set()
        try:
            from app.application.facades.session_facade import get_auth_service

            permissions.update(get_auth_service().get_user_permissions(user))
        except RECOVERABLE_ERRORS:
            permissions = set()

        # Market/admin-console sessions may not map role=admin on the User row;
        # promote from session account meta so Persy memory scope + cross-tenant work.
        try:
            from app.application.session_account_meta import is_session_market_admin
            from app.infrastructure.auth.dependencies import session_id_from_request

            sid = session_id_from_request(request)
            if sid and is_session_market_admin(sid):
                is_admin = True
                from app.application.session_account_meta import load_session_account_meta

                meta = load_session_account_meta(sid) or {}
                if not actor_id:
                    actor_id = str(
                        meta.get("username") or meta.get("market_username") or "admin"
                    ).strip()
                if not tenant:
                    tenant = str(meta.get("tenant_id") or "platform").strip() or "platform"
        except RECOVERABLE_ERRORS:
            pass

        if is_admin:
            permissions.add(DATASET_READ_PERMISSION)
            permissions.add(DATASET_WRITE_PERMISSION)
            try:
                from app.application.dataset_rag_app_service import DATASET_ADMIN_PERMISSION

                permissions.add(DATASET_ADMIN_PERMISSION)
            except RECOVERABLE_ERRORS:
                pass
            if not tenant:
                tenant = "platform"
            if not actor_id:
                actor_id = "admin"
        return DatasetAccessContext(
            actor_id=actor_id,
            tenant_id=tenant,
            permissions=frozenset(permissions),
            is_admin=is_admin,
        )

    if not _trusted_dataset_headers_enabled(request):
        if allow_local_default_read and _local_default_access_enabled(request):
            return DatasetAccessContext(
                actor_id="local-desktop",
                tenant_id="default",
                permissions=frozenset({DATASET_READ_PERMISSION}),
                is_admin=False,
            )
        return DatasetAccessContext()

    headers = request.headers
    tenant = (headers.get("X-Dataset-Tenant-ID") or headers.get("X-Tenant-ID") or "").strip()
    if not tenant:
        resolved_tenant = resolve_tenant_id(request)
        tenant = str(resolved_tenant) if resolved_tenant is not None else ""
    actor_id = (headers.get("X-Dataset-Actor-ID") or headers.get("X-User-ID") or "").strip()
    permissions_raw = headers.get("X-Dataset-Permissions") or headers.get("X-Permissions") or ""
    header_permissions = frozenset(
        part.strip() for part in permissions_raw.replace(";", ",").split(",") if part.strip()
    )
    is_admin = headers.get("X-Dataset-Admin", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if tenant or actor_id or header_permissions or is_admin:
        return DatasetAccessContext(
            actor_id=actor_id,
            tenant_id=tenant,
            permissions=header_permissions,
            is_admin=is_admin,
        )

    if allow_local_default_read and _local_default_access_enabled(request):
        return DatasetAccessContext(
            actor_id="local-desktop",
            tenant_id="default",
            permissions=frozenset({DATASET_READ_PERMISSION}),
            is_admin=False,
        )
    return DatasetAccessContext()


def require_legacy_global_knowledge(request: Request) -> None:
    """The old in-memory index has no tenant boundary; keep it platform-only."""
    if resolve_product_sku() != "enterprise":
        return
    user = get_logged_in_user(request)
    if not (
        getattr(user, "role", None) == "admin"
        and getattr(user, "tier", None) == "admin"
        and getattr(user, "tenant_id", None) is None
    ):
        raise HTTPException(403, "旧知识索引未提供租户隔离")
    from app.application.facades.session_facade import get_auth_service

    if not get_auth_service().has_permission(user, "dataset.admin"):
        raise HTTPException(403, "权限不足")


def require_desktop_knowledge_access(request: Request) -> None:
    """Require a real session and RBAC permission before desktop knowledge actions."""
    if not is_desktop_mode() or resolve_product_sku() != "enterprise":
        return
    path = request.url.path.rstrip("/")
    if path in {"/api/knowledge/v1/status", "/api/knowledge/v1/health"}:
        return
    user = get_logged_in_user(request)
    read = request.method in {"GET", "HEAD"} or path.endswith(("/query", "/versions/diff"))
    code = DATASET_READ_PERMISSION if read else DATASET_WRITE_PERMISSION
    from app.application.facades.session_facade import get_auth_service

    if not get_auth_service().has_permission(user, code):
        raise HTTPException(403, "权限不足")


def dataset_access_payload_from_request(
    request: Request,
    *,
    allow_local_default_read: bool = False,
) -> dict[str, Any]:
    context = dataset_access_context_from_request(
        request,
        allow_local_default_read=allow_local_default_read,
    )
    return context.to_dict() if context is not None else {}


def inject_trusted_dataset_access(
    runtime_context: dict[str, Any] | None,
    request: Request,
) -> dict[str, Any]:
    """Drop client claims and attach the server-derived access principal."""

    clean = {
        key: value
        for key, value in dict(runtime_context or {}).items()
        if key not in _CLIENT_ACCESS_KEYS
    }
    access = dataset_access_context_from_request(request, allow_local_default_read=True)
    if access is not None:
        clean["_dataset_access_context"] = access.to_dict()
        clean["_dataset_access_context_trusted"] = True
    return clean


def _trusted_dataset_headers_enabled(request: Request) -> bool:
    if is_desktop_mode():
        return False
    return deployment_is_test() or env_flag("XCAGI_TRUST_DATASET_ACCESS_HEADERS")


def _local_default_access_enabled(request: Request) -> bool:
    return deployment_is_test() and not is_desktop_mode()
