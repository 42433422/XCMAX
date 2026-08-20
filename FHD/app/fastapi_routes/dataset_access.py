"""Trusted dataset access context derived at the HTTP boundary."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from app.application.dataset_rag_app_service import (
    DATASET_READ_PERMISSION,
    DATASET_WRITE_PERMISSION,
    DatasetAccessContext,
)
from app.infrastructure.auth.dependencies import resolve_session_user
from app.infrastructure.auth.tenant_context import resolve_tenant_id
from app.utils.deployment import (
    deployment_is_production,
    deployment_is_staging,
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
        actor_id = str(getattr(user, "id", "") or "")
        tenant = str(getattr(user, "tenant_id", "") or "")
        role = str(getattr(user, "role", "") or "").strip().lower()
        is_admin = role in {"admin", "super_admin"}
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
                role = "admin"
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

        # Existing installations may predate dataset permissions in RBAC rows.
        # Preserve the established role policy while the bootstrap converges.
        if role in {"viewer", "operator", "user"}:
            permissions.add(DATASET_READ_PERMISSION)
        # A regular signed-in user owns knowledge inside their tenant and must
        # be able to grow Persy. Viewer remains the explicit read-only role.
        if role in {"operator", "user"}:
            permissions.add(DATASET_WRITE_PERMISSION)
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
        return None

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
    return None


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


def _is_local_request(request: Request) -> bool:
    if is_desktop_mode() or deployment_is_test():
        return True
    client = getattr(request, "client", None)
    host = str(getattr(client, "host", "") or "").strip().lower()
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}


def _trusted_dataset_headers_enabled(request: Request) -> bool:
    if env_flag("XCAGI_TRUST_DATASET_ACCESS_HEADERS"):
        return True
    if deployment_is_test() or is_desktop_mode():
        return True
    if deployment_is_production() or deployment_is_staging():
        return False
    return _is_local_request(request)


def _local_default_access_enabled(request: Request) -> bool:
    if deployment_is_test() or is_desktop_mode():
        return True
    if deployment_is_production() or deployment_is_staging():
        return False
    return _is_local_request(request)
