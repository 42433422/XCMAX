"""Protect globally stored shipment ETL from tenant accounts."""

from fastapi import HTTPException, Request

from app.mod_sdk.product_skus import resolve_product_sku
from app.utils.deployment import deployment_is_production, deployment_is_staging, env_flag


def require_legacy_shipment_etl_access(request: Request) -> None:
    enterprise = resolve_product_sku() == "enterprise"
    if not (
        enterprise
        or deployment_is_production()
        or deployment_is_staging()
        or env_flag("FHD_SHIPMENT_ETL_REQUIRE_RBAC")
    ):
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
