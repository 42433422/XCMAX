"""Keep tenant sessions away from legacy business APIs with global data stores."""

from __future__ import annotations

from fastapi import HTTPException, Request

from app.infrastructure.auth.dependencies import get_logged_in_user, resolve_session_user
from app.mod_sdk.product_skus import resolve_product_sku

_TENANT_SCOPED_PREFIXES = ("/api/print/label-jobs",)
_PRINTER_DEVICE_PATHS = frozenset(
    f"/api/print/{p}"
    for p in ("printers", "printer-selection", "default", "test", "validate", "diagnose")
) | {"/api/print/document-printer", "/api/print/label-printer", "/api/printers"}


def _permission_code(request: Request, read_code: str, write_code: str | None) -> str:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return read_code
    return write_code or read_code


def _request_path(request: Request) -> str:
    return request.url.path.rstrip("/") or "/"


def uses_tenant_scoped_store(request: Request) -> bool:
    path = _request_path(request)
    if path in {
        "/api/orders/webhooks",
        "/api/shipment/shipment-records/records",
        "/api/shipment/shipment-records/record",
        "/api/shipment/shipment-records/export",
    }:
        return True
    return any(
        path == prefix or path.startswith(prefix + "/") for prefix in _TENANT_SCOPED_PREFIXES
    )


def require_tenant_scoped_permission(read_code: str, write_code: str | None = None):
    def guard(request: Request):
        user = resolve_session_user(request)
        if user is None:
            return None
        if getattr(user, "tenant_id", None) is None:
            raise HTTPException(status_code=403, detail="该旧业务接口尚未提供安全的租户数据隔离")
        if resolve_product_sku() == "enterprise":
            from app.application.facades.session_facade import get_auth_service

            code = _permission_code(request, read_code, write_code)
            if not get_auth_service().has_permission(user, code):
                raise HTTPException(status_code=403, detail="权限不足")
        return user

    return guard


def check_legacy_business_user_permission(user, permission_code: str):
    """The existing legacy-store policy, shared by HTTP and authenticated tools.

    This preserves local HTTP anonymous behavior. Tool callers must establish
    their authenticated actor separately before using this policy.
    """
    if resolve_product_sku() != "enterprise":
        if user is not None and user.tenant_id is not None:
            raise HTTPException(status_code=403, detail="该旧业务接口尚未提供安全的租户数据隔离")
        return None
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录")
    if user.tenant_id is not None or user.role != "admin" or user.tier != "admin":
        raise HTTPException(status_code=403, detail="该旧业务接口尚未提供安全的租户数据隔离")
    from app.application.facades.session_facade import get_auth_service

    if not get_auth_service().has_permission(user, permission_code):
        raise HTTPException(status_code=403, detail="权限不足")
    return user


def require_scoped_business_permission(read_code: str, write_code: str | None = None):
    def guard(request: Request):
        if uses_tenant_scoped_store(request):
            return require_tenant_scoped_permission(read_code, write_code)(request)
        user = (
            get_logged_in_user(request)
            if resolve_product_sku() == "enterprise"
            else resolve_session_user(request)
        )
        return check_legacy_business_user_permission(
            user, _permission_code(request, read_code, write_code)
        )

    return guard


def require_print_permission(code: str = "print.label"):
    """本机打印机路径不含租户业务数据：租户会话凭权限即可访问，其余打印路径仍走租户门禁。"""
    scoped = require_scoped_business_permission(code)

    def guard(request: Request):
        if request.url.path.rstrip("/") not in _PRINTER_DEVICE_PATHS:
            return scoped(request)
        if resolve_product_sku() != "enterprise":
            return None
        user = get_logged_in_user(request)
        from app.application.facades.session_facade import get_auth_service

        if not get_auth_service().has_permission(user, code):
            raise HTTPException(status_code=403, detail="权限不足")
        return user

    return guard


def check_owned_business_permission(user, permission_code: str) -> int:
    """New reviewed tool paths only; legacy HTTP policy remains unchanged."""
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录")
    if resolve_product_sku() != "enterprise":
        raise HTTPException(status_code=403, detail="此企业隔离工具仅适用于企业版")
    tenant = getattr(user, "tenant_id", None)
    if type(tenant) is not int or tenant <= 0:
        raise HTTPException(status_code=403, detail="操作需要已认证企业归属")
    from app.application.facades.session_facade import get_auth_service

    if permission_code not in get_auth_service().get_user_permissions(user):
        raise HTTPException(status_code=403, detail="权限不足")
    return tenant
