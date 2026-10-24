"""Tenant and permission admission for dataset operations."""

from __future__ import annotations

from typing import Any

from app.application.dataset_rag.models import DatasetAccessContext, _clean_key

DATASET_READ_PERMISSION = "dataset.read"
DATASET_WRITE_PERMISSION = "dataset.write"
DATASET_ADMIN_PERMISSION = "dataset.admin"


def _coerce_access_context(
    value: DatasetAccessContext | dict[str, Any] | None,
) -> DatasetAccessContext | None:
    if value is None:
        return None
    if isinstance(value, DatasetAccessContext):
        return value
    permissions_value = value.get("permissions") if isinstance(value, dict) else None
    if isinstance(permissions_value, str):
        permissions = frozenset(
            part.strip() for part in permissions_value.replace(";", ",").split(",") if part.strip()
        )
    elif isinstance(permissions_value, (list, tuple, set, frozenset)):
        permissions = frozenset(
            str(part).strip() for part in permissions_value if str(part).strip()
        )
    else:
        permissions = frozenset()
    return DatasetAccessContext(
        actor_id=str(value.get("actor_id") or value.get("user_id") or ""),
        tenant_id=_clean_key(str(value.get("tenant_id") or ""), default="")
        if value.get("tenant_id")
        else "",
        permissions=permissions,
        is_admin=bool(value.get("is_admin") or value.get("admin")),
    )


def _has_dataset_permission(context: DatasetAccessContext | None, permission: str) -> bool:
    if context is None:
        return True
    if context.is_admin or DATASET_ADMIN_PERMISSION in context.permissions:
        return True
    if permission in context.permissions:
        return True
    prefix = permission.split(".", 1)[0]
    return f"{prefix}.*" in context.permissions or "*" in context.permissions


def _dataset_permission_denied(
    *, dataset_id: str, permission: str, message: str, context: DatasetAccessContext | None
) -> dict[str, Any]:
    return {
        "success": False,
        "dataset_id": dataset_id,
        "error_code": "dataset_permission_denied",
        "message": message,
        "required_permission": permission,
        "access": context.to_dict() if context is not None else {},
    }


def _ensure_dataset_permission(
    context: DatasetAccessContext | None, permission: str, *, dataset_id: str
) -> dict[str, Any] | None:
    if _has_dataset_permission(context, permission):
        return None
    return _dataset_permission_denied(
        dataset_id=dataset_id,
        permission=permission,
        message=f"{permission} permission is required",
        context=context,
    )


def _ensure_tenant_allowed(
    context: DatasetAccessContext | None, tenant_id: str, *, dataset_id: str, operation: str
) -> dict[str, Any] | None:
    if context is None or context.is_admin or DATASET_ADMIN_PERMISSION in context.permissions:
        return None
    actor_tenant = _clean_key(context.tenant_id, default="") if context.tenant_id else ""
    target_tenant = _clean_key(str(tenant_id or ""), default="") if tenant_id else ""
    if not actor_tenant:
        return _dataset_permission_denied(
            dataset_id=dataset_id,
            permission=DATASET_READ_PERMISSION,
            message=f"{operation} requires an actor tenant context",
            context=context,
        )
    if not target_tenant:
        return _dataset_permission_denied(
            dataset_id=dataset_id,
            permission=DATASET_ADMIN_PERMISSION,
            message=f"{operation} across all tenants requires dataset admin",
            context=context,
        )
    if actor_tenant != target_tenant:
        return _dataset_permission_denied(
            dataset_id=dataset_id,
            permission=DATASET_ADMIN_PERMISSION,
            message=f"{operation} cannot access tenant {target_tenant}",
            context=context,
        )
    return None


def _resolve_tenant_for_access(
    access_context: DatasetAccessContext | dict[str, Any] | None,
    requested_tenant_id: str,
    *,
    required_permission: str,
    default_without_context: str,
    dataset_id: str,
) -> tuple[str, dict[str, Any] | None]:
    context = _coerce_access_context(access_context)
    denied = _ensure_dataset_permission(context, required_permission, dataset_id=dataset_id)
    if denied is not None:
        return ("", denied)
    requested = (
        _clean_key(str(requested_tenant_id or ""), default="") if requested_tenant_id else ""
    )
    if context is None:
        if requested:
            return (requested, None)
        return (
            _clean_key(str(default_without_context), default=default_without_context)
            if default_without_context
            else "",
            None,
        )
    if context.is_admin or DATASET_ADMIN_PERMISSION in context.permissions:
        if requested:
            return (requested, None)
        return (
            _clean_key(str(default_without_context), default=default_without_context)
            if default_without_context
            else "",
            None,
        )
    actor_tenant = _clean_key(context.tenant_id, default="") if context.tenant_id else ""
    if not actor_tenant:
        return (
            "",
            _dataset_permission_denied(
                dataset_id=dataset_id,
                permission=required_permission,
                message="dataset tenant context is required",
                context=context,
            ),
        )
    if requested and requested != actor_tenant:
        return (
            "",
            _dataset_permission_denied(
                dataset_id=dataset_id,
                permission=DATASET_ADMIN_PERMISSION,
                message=f"tenant {requested} is outside requester scope",
                context=context,
            ),
        )
    return (actor_tenant, None)
