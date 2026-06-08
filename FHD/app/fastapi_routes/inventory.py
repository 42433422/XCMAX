"""
库存管理 API 路由 — HTTP 薄层，委托 InventoryAppService。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Query

logger = logging.getLogger(__name__)

router = APIRouter(tags=["inventory"])


def _svc():
    from app.application.inventory_app_service import InventoryAppService

    return InventoryAppService()


@router.get("/api/inventory")
def inventory_list(
    warehouse_id: int | None = Query(default=None),
    product_id: int | None = Query(default=None),
    batch_no: str | None = Query(default=None),
    page: int = Query(default=1),
    per_page: int = Query(default=50),
):
    return _svc().get_inventory(
        warehouse_id=warehouse_id,
        product_id=product_id,
        batch_no=batch_no,
        page=page,
        per_page=per_page,
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
def inventory_locations_post(body: dict = Body(default_factory=dict)):
    return _svc().create_storage_location(body or {})


@router.put("/api/inventory/locations/{location_id}")
def inventory_locations_put(location_id: int, body: dict = Body(default_factory=dict)):
    return _svc().update_storage_location(location_id, body or {})


@router.get("/api/inventory/warehouses")
def inventory_warehouses_list(status: str | None = Query(default=None)):
    return _svc().get_warehouses(status=status)


@router.get("/api/inventory/warehouses/{warehouse_id}")
def inventory_warehouses_get(warehouse_id: int):
    return _svc().get_warehouse(warehouse_id)


@router.post("/api/inventory/warehouses")
def inventory_warehouses_post(body: dict = Body(default_factory=dict)):
    return _svc().create_warehouse(body or {})


@router.put("/api/inventory/warehouses/{warehouse_id}")
def inventory_warehouses_put(warehouse_id: int, body: dict = Body(default_factory=dict)):
    return _svc().update_warehouse(warehouse_id, body or {})


@router.delete("/api/inventory/warehouses/{warehouse_id}")
def inventory_warehouses_delete(warehouse_id: int):
    return _svc().delete_warehouse(warehouse_id)


@router.post("/api/inventory/in")
def inventory_in(body: dict = Body(default_factory=dict)):
    data = body or {}
    return _svc().inventory_in(
        product_id=data.get("product_id"),
        warehouse_id=data.get("warehouse_id"),
        quantity=float(data.get("quantity", 0)),
        batch_no=data.get("batch_no"),
        location_id=data.get("location_id"),
        unit_price=float(data["unit_price"]) if data.get("unit_price") is not None else None,
        reference_type=data.get("reference_type"),
        reference_id=data.get("reference_id"),
        operator=data.get("operator"),
        remark=data.get("remark"),
    )


@router.post("/api/inventory/out")
def inventory_out(body: dict = Body(default_factory=dict)):
    data = body or {}
    return _svc().inventory_out(
        product_id=data.get("product_id"),
        warehouse_id=data.get("warehouse_id"),
        quantity=float(data.get("quantity", 0)),
        batch_no=data.get("batch_no"),
        location_id=data.get("location_id"),
        unit_price=float(data["unit_price"]) if data.get("unit_price") is not None else None,
        reference_type=data.get("reference_type"),
        reference_id=data.get("reference_id"),
        operator=data.get("operator"),
        remark=data.get("remark"),
    )


@router.post("/api/inventory/transfer")
def inventory_transfer(body: dict = Body(default_factory=dict)):
    data = body or {}
    return _svc().inventory_transfer(
        product_id=data.get("product_id"),
        from_warehouse_id=data.get("from_warehouse_id"),
        to_warehouse_id=data.get("to_warehouse_id"),
        quantity=float(data.get("quantity", 0)),
        batch_no=data.get("batch_no"),
        from_location_id=data.get("from_location_id"),
        to_location_id=data.get("to_location_id"),
        operator=data.get("operator"),
        remark=data.get("remark"),
    )
