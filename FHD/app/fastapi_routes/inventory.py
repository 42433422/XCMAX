"""
库存管理 API 路由 — HTTP 薄层，委托 InventoryAppService。
"""

from __future__ import annotations

from typing import Any

from fastapi import Body, Query, Request
from fastapi.responses import JSONResponse

from app.fastapi_routes.inventory_exports import router as export_router
from app.fastapi_routes.tools_execute import run_tools_execute_agent

router = export_router


def _svc():
    from app.application.inventory_app_service import InventoryAppService

    return InventoryAppService()


def _run_inventory_agent(
    *,
    request: Request,
    action: str,
    params: dict[str, Any],
    route_path: str,
) -> JSONResponse:
    result, status = run_tools_execute_agent(
        request=request,
        body={"tool_id": "inventory", "action": action, "params": params},
        route_path=route_path,
    )
    return JSONResponse(result, status_code=status)


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


@router.get("/api/inventory")
def inventory_list(
    warehouse_id: int | None = Query(default=None),
    product_id: int | None = Query(default=None),
    batch_no: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=1000),
    keyword: str | None = Query(default=None, max_length=200),
):
    return _svc().get_inventory(
        warehouse_id=warehouse_id,
        product_id=product_id,
        batch_no=batch_no,
        page=page,
        per_page=per_page,
        keyword=keyword,
    )


@router.get("/api/inventory/summary")
def inventory_summary(warehouse_id: int | None = Query(default=None)):
    return _svc().get_inventory_summary(warehouse_id=warehouse_id)


@router.get("/api/inventory/transactions")
def inventory_transactions(
    product_id: int | None = Query(default=None),
    warehouse_id: int | None = Query(default=None),
    transaction_type: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    page: int = Query(default=1),
    per_page: int = Query(default=50),
):
    svc = _svc()
    return svc.get_inventory_transactions(
        product_id=product_id,
        warehouse_id=warehouse_id,
        transaction_type=transaction_type,
        start_date=svc.parse_optional_datetime(start_date),
        end_date=svc.parse_optional_datetime(end_date),
        page=page,
        per_page=per_page,
    )


@router.get("/api/inventory/inventory/alert")
def inventory_alert():
    return _svc().get_inventory_alert()


@router.get("/api/inventory/alert")
def inventory_alert_alias():
    return _svc().get_inventory_alert()


@router.get("/api/inventory/combined-alert")
def inventory_combined_alert(threshold: float | None = None):
    return _svc().get_combined_alert(threshold=threshold)


@router.get("/api/inventory/locations")
def inventory_locations(
    warehouse_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
):
    if not warehouse_id:
        return {"success": False, "message": "仓库ID不能为空"}
    return _svc().get_storage_locations(warehouse_id=warehouse_id, status=status)


@router.post("/api/inventory/locations")
def inventory_locations_post(request: Request, body: dict = Body(default_factory=dict)):
    return _run_inventory_agent(
        request=request,
        action="create_storage_location",
        params=dict(body or {}),
        route_path="/api/inventory/locations",
    )


@router.put("/api/inventory/locations/{location_id}")
def inventory_locations_put(
    request: Request,
    location_id: int,
    body: dict = Body(default_factory=dict),
):
    return _run_inventory_agent(
        request=request,
        action="update_storage_location",
        params={"location_id": location_id, **dict(body or {})},
        route_path="/api/inventory/locations/{location_id}",
    )


def _warehouse_setup_user(request: Request, permission_code: str) -> Any:
    """仓库初始化只对已登录且有企业归属的会话开放，并按企业 SKU 做 RBAC。"""
    from fastapi import HTTPException

    from app.infrastructure.auth.dependencies import get_logged_in_user
    from app.mod_sdk.product_skus import resolve_product_sku

    user = get_logged_in_user(request)
    if getattr(user, "tenant_id", None) is None:
        raise HTTPException(status_code=403, detail="企业归属缺失")
    if resolve_product_sku() == "enterprise":
        from app.application.facades.session_facade import get_auth_service

        if not get_auth_service().has_permission(user, permission_code):
            raise HTTPException(status_code=403, detail="权限不足")
    return user


@router.get("/api/inventory/setup/warehouse")
def inventory_warehouse_setup_status(request: Request):
    """当前企业是否已有可用仓库（新装或旧版升级后没有仓库时，前端据此显示引导）。"""
    from app.application.inventory_default_warehouse import warehouse_setup_status
    from app.db.session import get_db

    user = _warehouse_setup_user(request, "shipment.view")
    with get_db() as db:
        status = warehouse_setup_status(db, int(user.tenant_id))
    return {"success": True, "data": status}


@router.post("/api/inventory/setup/warehouse")
def inventory_warehouse_setup_init(request: Request):
    """通过统一权限和审批初始化当前企业默认仓库。"""
    return _run_inventory_agent(
        request=request,
        action="setup_warehouse",
        params={},
        route_path="/api/inventory/setup/warehouse",
    )


@router.get("/api/inventory/warehouses")
def inventory_warehouses_list(status: str | None = Query(default=None)):
    return _svc().get_warehouses(status=status)


@router.get("/api/inventory/warehouses/{warehouse_id}")
def inventory_warehouses_get(warehouse_id: int):
    return _svc().get_warehouse(warehouse_id)


@router.post("/api/inventory/warehouses")
def inventory_warehouses_post(request: Request, body: dict = Body(default_factory=dict)):
    return _run_inventory_agent(
        request=request,
        action="create_warehouse",
        params=dict(body or {}),
        route_path="/api/inventory/warehouses",
    )


@router.put("/api/inventory/warehouses/{warehouse_id}")
def inventory_warehouses_put(
    request: Request,
    warehouse_id: int,
    body: dict = Body(default_factory=dict),
):
    return _run_inventory_agent(
        request=request,
        action="update_warehouse",
        params={"warehouse_id": warehouse_id, **dict(body or {})},
        route_path="/api/inventory/warehouses/{warehouse_id}",
    )


@router.delete("/api/inventory/warehouses/{warehouse_id}")
def inventory_warehouses_delete(request: Request, warehouse_id: int):
    return _run_inventory_agent(
        request=request,
        action="delete_warehouse",
        params={"warehouse_id": warehouse_id},
        route_path="/api/inventory/warehouses/{warehouse_id}",
    )


@router.post("/api/inventory/in")
def inventory_in(request: Request, body: dict = Body(default_factory=dict)):
    data = body or {}
    return _run_inventory_agent(
        request=request,
        action="stock_in",
        params={
            "product_id": data.get("product_id"),
            "warehouse_id": data.get("warehouse_id"),
            "quantity": float(data.get("quantity", 0)),
            **{
                key: _float_or_none(data[key]) if key == "unit_price" else data[key]
                for key in (
                    "batch_no",
                    "location_id",
                    "unit_price",
                    "reference_type",
                    "reference_id",
                    "operator",
                    "remark",
                )
                if key in data
            },
        },
        route_path="/api/inventory/in",
    )


@router.post("/api/inventory/out")
def inventory_out(request: Request, body: dict = Body(default_factory=dict)):
    data = body or {}
    return _run_inventory_agent(
        request=request,
        action="stock_out",
        params={
            "product_id": data.get("product_id"),
            "warehouse_id": data.get("warehouse_id"),
            "quantity": float(data.get("quantity", 0)),
            **{
                key: _float_or_none(data[key]) if key == "unit_price" else data[key]
                for key in (
                    "batch_no",
                    "location_id",
                    "unit_price",
                    "reference_type",
                    "reference_id",
                    "operator",
                    "remark",
                )
                if key in data
            },
        },
        route_path="/api/inventory/out",
    )


@router.post("/api/inventory/transfer")
def inventory_transfer(request: Request, body: dict = Body(default_factory=dict)):
    data = body or {}
    return _run_inventory_agent(
        request=request,
        action="transfer",
        params={
            "product_id": data.get("product_id"),
            "from_warehouse_id": data.get("from_warehouse_id"),
            "to_warehouse_id": data.get("to_warehouse_id"),
            "quantity": float(data.get("quantity", 0)),
            **{
                key: data[key]
                for key in ("batch_no", "from_location_id", "to_location_id", "operator", "remark")
                if key in data
            },
        },
        route_path="/api/inventory/transfer",
    )
