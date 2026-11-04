"""Object authorization for local payment operations, independent of actor roles."""

from typing import Any

from fastapi import HTTPException, Request

from app.infrastructure.auth.dependencies import get_logged_in_user
from app.infrastructure.payment import order_store
from app.infrastructure.payment.payment_sot import (
    is_fhd_postgres_payment_sot,
    is_modstore_payment_sot,
)


def require_local_payment_backend() -> None:
    if is_modstore_payment_sot():
        raise HTTPException(status_code=409, detail="请使用市场账号的支付接口")
    if is_fhd_postgres_payment_sot():
        raise HTTPException(
            status_code=503, detail="本地 PostgreSQL 订单存储尚未实现，拒绝回退 JSON"
        )


def owned_payment_order(
    request: Request, out_trade_no: str, *, permission: str | None = None
) -> dict[str, Any]:
    user = get_logged_in_user(request)
    require_local_payment_backend()
    order = order_store.get_order(out_trade_no)
    owner = order.get("local_user_id") if order else None
    tenant = order.get("tenant_id") if order else None
    if (
        not order
        or order.get("out_trade_no") != out_trade_no
        or type(owner) is not int
        or owner <= 0
        or owner != user.id
        or "tenant_id" not in order
        or (tenant is not None and (type(tenant) is not int or tenant <= 0))
        or tenant != user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="订单不存在")
    if permission:
        from app.application.facades.session_facade import get_auth_service

        if not get_auth_service().has_permission(user, permission):
            raise HTTPException(status_code=403, detail="缺少订单操作权限")
    return order
