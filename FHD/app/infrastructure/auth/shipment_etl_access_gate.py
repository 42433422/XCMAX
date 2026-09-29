"""Protect globally stored shipment ETL from tenant accounts."""

from fastapi import HTTPException, Request

from app.mod_sdk.product_skus import resolve_product_sku
from app.utils.deployment import deployment_is_production, deployment_is_staging, env_flag


def _shipment_etl_must_check() -> bool:
    enterprise = resolve_product_sku() == "enterprise"
    return bool(
        enterprise
        or deployment_is_production()
        or deployment_is_staging()
        or env_flag("FHD_SHIPMENT_ETL_REQUIRE_RBAC")
    )


def require_tenant_etl_preview(request: Request) -> None:
    """OCR preview of an uploaded file, scoped to the session tenant.

    Global execute/batch routes stay on ``require_legacy_shipment_etl_access``.
    """
    if not _shipment_etl_must_check():
        return
    from app.application.facades.session_facade import get_auth_service
    from app.infrastructure.auth.dependencies import get_logged_in_user

    user = get_logged_in_user(request)
    if getattr(user, "tenant_id", None) is None:
        raise HTTPException(403, "旧送货单 ETL 未提供租户数据隔离")
    auth = get_auth_service()
    if not (
        auth.has_permission(user, "etl.execute") or auth.has_permission(user, "shipment.create")
    ):
        raise HTTPException(403, "权限不足")


def require_legacy_shipment_etl_access(request: Request) -> None:
    enterprise = resolve_product_sku() == "enterprise"
    if not _shipment_etl_must_check():
        return
    from app.application.facades.session_facade import get_auth_service
    from app.infrastructure.auth.dependencies import get_logged_in_user

    user = get_logged_in_user(request)
    if enterprise and not (
        getattr(user, "role", None) == "admin"
        and getattr(user, "tier", None) == "admin"
        and getattr(user, "tenant_id", None) is None
    ):
        raise HTTPException(403, "旧送货单 ETL 未提供租户数据隔离")
    if not get_auth_service().has_permission(user, "shipment.create"):
        raise HTTPException(403, "权限不足")
