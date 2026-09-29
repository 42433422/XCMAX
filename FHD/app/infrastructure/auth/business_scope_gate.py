"""Keep tenant sessions away from legacy business APIs with global data stores."""

from __future__ import annotations

from fastapi import HTTPException, Request

from app.infrastructure.auth.dependencies import get_logged_in_user, resolve_session_user
from app.mod_sdk.product_skus import resolve_product_sku


def require_scoped_business_permission(read_code: str, write_code: str | None = None):
    def guard(request: Request):
        if resolve_product_sku() != "enterprise":
            user = resolve_session_user(request)
            if user is not None and user.tenant_id is not None:
                raise HTTPException(
                    status_code=403, detail="该旧业务接口尚未提供安全的租户数据隔离"
                )
            return None
        user = get_logged_in_user(request)
        if user.tenant_id is not None or user.role != "admin" or user.tier != "admin":
            raise HTTPException(status_code=403, detail="该旧业务接口尚未提供安全的租户数据隔离")
        from app.application.facades.session_facade import get_auth_service

        code = (
            read_code if request.method in {"GET", "HEAD", "OPTIONS"} else write_code or read_code
        )
        if not get_auth_service().has_permission(user, code):
            raise HTTPException(status_code=403, detail="权限不足")
        return user

    return guard
