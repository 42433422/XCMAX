"""Historical ``/api/orders`` routes mounted on the shipment router."""

from __future__ import annotations

import sys
from typing import Any

from fastapi import Body, Query, Request


def _facade() -> Any:
    return sys.modules["app.fastapi_routes.shipment_orders"]


router = _facade().router


@router.get("/api/orders")
def api_orders_list(limit: int = Query(default=100, ge=1, le=5000)):
    orders = _facade()._svc().get_orders(limit=limit) or []
    return {"success": True, "data": orders, "count": len(orders)}


@router.post("/api/orders", status_code=201)
def api_orders_create(request: Request, payload: dict[str, Any] = Body(default_factory=dict)):
    """Create the shipment record shown by the desktop Orders page."""
    purchase_unit = str(
        payload.get("purchase_unit")
        or payload.get("unit_name")
        or payload.get("customer_name")
        or ""
    ).strip()
    products = payload.get("products") or payload.get("items") or []
    if not purchase_unit:
        raise _facade().HTTPException(status_code=400, detail="缺少购买单位")
    if not isinstance(products, list) or not products:
        raise _facade().HTTPException(status_code=400, detail="产品列表不能为空")
    result = _facade()._run_shipment_records_agent(
        request=request,
        action="create",
        params={
            "unit_name": purchase_unit,
            "products": products,
            "contact_person": payload.get("contact_person"),
            "contact_phone": payload.get("contact_phone"),
        },
        route_path="/api/orders",
    )
    return _facade().JSONResponse(result, status_code=201 if result.get("success") else 400)


@router.delete("/api/orders")
@router.delete("/api/orders/", include_in_schema=False)
def api_orders_delete_root(request: Request):
    result = _facade()._run_shipment_orders_agent(
        request=request, action="clear_all", params={}, route_path="/api/orders"
    )
    return _facade().JSONResponse(result, status_code=200 if result.get("success") else 500)


@router.get("/api/orders/latest")
def api_orders_latest():
    orders = _facade()._svc().get_orders(limit=10) or []
    return {"success": True, "data": orders, "count": len(orders)}


@router.get("/api/orders/search")
def api_orders_search(q: str = Query(default="")):
    qs = (q or "").strip()
    rows = _facade()._svc().search_orders(qs) if qs else []
    return {"success": True, "data": rows, "count": len(rows)}


@router.post("/api/orders/set-sequence")
def api_orders_set_sequence(request: Request, payload: dict[str, Any] = Body(default_factory=dict)):
    result = _facade()._run_shipment_orders_agent(
        request=request,
        action="set_sequence",
        params={"sequence": int(payload.get("sequence", 1))},
        route_path="/api/orders/set-sequence",
    )
    return _facade().JSONResponse(result, status_code=200 if result.get("success") else 500)


@router.post("/api/orders/reset-sequence")
def api_orders_reset_sequence(request: Request):
    result = _facade()._run_shipment_orders_agent(
        request=request, action="reset_sequence", params={}, route_path="/api/orders/reset-sequence"
    )
    return _facade().JSONResponse(result, status_code=200 if result.get("success") else 500)


@router.get("/api/orders/purchase-units")
def api_orders_purchase_units():
    units = _facade()._svc().get_purchase_units()
    return {"success": True, "data": units, "count": len(units)}


@router.post("/api/orders/clear-shipment")
def api_orders_clear_shipment(
    request: Request, payload: dict[str, Any] = Body(default_factory=dict)
):
    purchase_unit = str(payload.get("purchase_unit") or "").strip()
    if not purchase_unit:
        raise _facade().HTTPException(status_code=400, detail="缺少购买单位参数")
    result = _facade()._run_shipment_orders_agent(
        request=request,
        action="clear_shipment",
        params={"purchase_unit": purchase_unit},
        route_path="/api/orders/clear-shipment",
    )
    return _facade().JSONResponse(result, status_code=200 if result.get("success") else 500)


@router.get("/api/orders/export")
def api_orders_export(
    unit: str | None = Query(default=None),
    purchase_unit: str | None = Query(default=None),
    template_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
):
    selected_unit = (unit or purchase_unit or "").strip() or None
    result = (
        _facade()
        ._svc()
        .export_shipment_records(
            unit_name=selected_unit, template_id=template_id, status_filter=status
        )
    )
    file_path = _facade()._safe_shipment_export_path(result)
    if result.get("success") and file_path:
        return _facade().FileResponse(
            file_path,
            filename=_facade().os.path.basename(file_path),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    return _facade().JSONResponse(result, status_code=400 if not result.get("success") else 500)


@router.delete("/api/orders/clear-all")
def api_orders_clear_all(request: Request):
    result = _facade()._run_shipment_orders_agent(
        request=request, action="clear_all", params={}, route_path="/api/orders/clear-all"
    )
    return _facade().JSONResponse(result, status_code=200 if result.get("success") else 500)


@router.patch("/api/orders/{order_number}")
def api_orders_update(
    request: Request, order_number: str, payload: dict[str, Any] = Body(default_factory=dict)
):
    try:
        record_id = int(order_number)
    except ValueError:
        raise _facade().HTTPException(status_code=404, detail="订单不存在")
    requested_status = payload.get("status")
    if requested_status is not None and str(requested_status) not in {
        "pending",
        "printed",
        "completed",
        "cancelled",
    }:
        raise _facade().HTTPException(status_code=400, detail="无效的订单状态")
    update_params = {
        "id": record_id,
        "unit_name": payload.get("purchase_unit") or payload.get("unit_name"),
        "product_name": payload.get("product_name"),
        "model_number": payload.get("model_number"),
        "quantity_kg": payload.get("quantity_kg"),
        "quantity_tins": payload.get("quantity_tins"),
        "tin_spec": payload.get("tin_spec"),
        "unit_price": payload.get("unit_price"),
        "amount": payload.get("amount"),
        "status": requested_status,
    }
    result = _facade()._run_shipment_records_agent(
        request=request,
        action="update",
        params={key: value for (key, value) in update_params.items() if value is not None},
        route_path="/api/orders/{order_number}",
    )
    if not result.get("success"):
        return _facade().JSONResponse(result, status_code=404)
    result["data"] = _facade()._svc().get_order(str(record_id))
    return _facade().JSONResponse(_facade().jsonable_encoder(result), status_code=200)


@router.get("/api/orders/{order_number}")
def api_orders_get(order_number: str):
    try:
        int(order_number)
    except ValueError:
        raise _facade().HTTPException(status_code=404, detail="订单不存在")
    order = _facade()._svc().get_order(str(order_number))
    if not order:
        raise _facade().HTTPException(status_code=404, detail="订单不存在")
    return {"success": True, "data": order}


@router.delete("/api/shipment/orders/{order_number}")
def shipment_orders_delete(request: Request, order_number: str):
    try:
        shipment_id = int(order_number)
    except ValueError:
        raise _facade().HTTPException(status_code=400, detail=f"无效的订单编号格式：{order_number}")
    result = _facade()._run_shipment_orders_agent(
        request=request,
        action="delete",
        params={"id": shipment_id, "order_number": order_number},
        route_path="/api/shipment/orders/{order_number}",
    )
    if not result.get("success"):
        raise _facade().HTTPException(status_code=400, detail=result.get("message", "删除失败"))
    result["message"] = f"订单 {order_number} 已删除"
    return result
