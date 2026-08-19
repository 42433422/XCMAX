"""
出货单 / 订单 / 出货记录 —— 继承自归档 ``ai_assistant_compat`` + ``shipment`` 蓝图端点契约的 FastAPI 补全。

覆盖：

- ``/api/orders*``、``/orders/next_number``（AI 助手根路径）
- ``/api/shipment/generate|print|download/*`` 与 ``/api/shipment/orders*``（与归档 ``shipment`` 蓝图对齐）
- ``GET /api/shipment/list`` 统一注册
- ``/api/shipment/shipment-records/*``

历史：统一 FastAPI 入口后兼容层未挂载上述路径时，前端会出现大量 404。
"""

from __future__ import annotations

import importlib
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse

from app.application.facades.query_facade import query_service
from app.bootstrap import get_shipment_application_service_core
from app.db.models import ShipmentRecord
from app.fastapi_routes import shipment_agent_runtime as _shipment_agent_runtime
from app.utils.operational_errors import RECOVERABLE_ERRORS

_agent_node_output = _shipment_agent_runtime.agent_node_output
_shipment_agent_user_id = _shipment_agent_runtime.shipment_agent_user_id
_run_shipment_records_agent = _shipment_agent_runtime.run_shipment_records_agent
_run_shipment_orders_agent = _shipment_agent_runtime.run_shipment_orders_agent

logger = logging.getLogger(__name__)

router = APIRouter(tags=["shipment-orders-compat"])


def _svc():
    return get_shipment_application_service_core()


def _safe_shipment_export_path(result: dict[str, Any]) -> str | None:
    from pathlib import Path

    from app.infrastructure.workspace import resolve_existing_file_under_root
    from app.utils.path_io.path_utils import get_data_dir

    filename = os.path.basename(str(result.get("filename") or ""))
    if not re.fullmatch(r"shipment_records_[^/\\]{1,160}_\d{8}_\d{6}\.xlsx", filename):
        return None
    try:
        candidate = resolve_existing_file_under_root(
            Path(get_data_dir()).resolve() / "exports", filename
        )
    except (OSError, ValueError):
        return None
    return str(candidate)


def _next_order_number_payload(suffix: str = "A") -> dict[str, Any]:
    today = datetime.now()
    year = today.strftime("%y")
    month = today.strftime("%m")
    start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (start + timedelta(days=32)).replace(day=1)
    count = query_service.count(
        ShipmentRecord,
        created_at__gte=start,
        created_at__lt=next_month,
    )
    next_sequence = int(count) + 1
    order_number = f"{year}-{month}-{next_sequence:05d}{suffix}"
    return {
        "success": True,
        "data": {
            "order_number": order_number,
            "sequence": next_sequence,
            "year_month": f"{year}-{month}",
        },
    }


@router.get("/orders/next_number")
def orders_next_number_root(suffix: str = Query(default="A")):
    return _next_order_number_payload(suffix)


@router.get("/api/shipment/orders/next_number")
def orders_next_number_under_shipment(suffix: str = Query(default="A")):
    # 与归档 ``shipment.get_next_order_number`` 一致：后缀须为单个大写字母，否则回退 A
    suf = (suffix or "").strip().upper()
    if not (len(suf) == 1 and re.fullmatch(r"[A-Z]", suf)):
        suf = "A"
    return _next_order_number_payload(suf)


@router.get("/api/orders/next_number")
def orders_next_number_under_api(suffix: str = Query(default="A")):
    return _next_order_number_payload(suffix)


# ----- /api/shipment（归档 shipment 蓝图，与 /api/orders* 镜像）-----


@router.post("/api/shipment/generate-batch")
def shipment_generate_batch(request: Request, payload: dict[str, Any] = Body(default_factory=dict)):
    """批量生成：兼容测试与旧前端字段（customer_name / items）。"""
    shipments = payload.get("shipments") or []
    if not shipments:
        raise HTTPException(status_code=400, detail="shipments 不能为空")
    result = _run_shipment_orders_agent(
        request=request,
        action="generate_batch",
        params={"shipments": shipments},
        route_path="/api/shipment/generate-batch",
    )
    return JSONResponse(jsonable_encoder(result), status_code=200)


@router.post("/api/shipment/generate")
def shipment_generate(request: Request, payload: dict[str, Any] = Body(default_factory=dict)):
    unit_name = str(payload.get("unit_name") or "").strip()
    products = payload.get("products") or []
    date = payload.get("date")
    if not unit_name:
        raise HTTPException(status_code=400, detail="单位名称不能为空")
    if not products:
        raise HTTPException(status_code=400, detail="产品列表不能为空")
    try:
        result = _run_shipment_orders_agent(
            request=request,
            action="generate",
            params={"unit_name": unit_name, "products": products, "date": date},
            route_path="/api/shipment/generate",
        )
        return JSONResponse(result, status_code=200 if result.get("success") else 500)
    except RECOVERABLE_ERRORS as e:
        logger.exception("shipment generate: %s", e)
        return JSONResponse(
            {"success": False, "message": f"生成失败：{str(e)}"},
            status_code=500,
        )


@router.post("/api/shipment/print")
def shipment_print(request: Request, payload: dict[str, Any] = Body(default_factory=dict)):
    file_path = payload.get("file_path")
    order_id = payload.get("order_id")
    printer_name = payload.get("printer_name")

    if not file_path:
        raise HTTPException(status_code=400, detail="文件路径不能为空")
    if not os.path.exists(str(file_path)):
        raise HTTPException(status_code=404, detail="文件不存在")

    try:
        if order_id:
            try:
                int(order_id)
            except RECOVERABLE_ERRORS:
                raise HTTPException(status_code=400, detail="order_id 无效")
        result = _run_shipment_orders_agent(
            request=request,
            action="print",
            params={
                "file_path": str(file_path),
                "order_id": order_id,
                "printer_name": printer_name,
            },
            route_path="/api/shipment/print",
        )
        return JSONResponse(result, status_code=200 if result.get("success") else 500)
    except HTTPException:
        raise
    except RECOVERABLE_ERRORS as e:
        logger.exception("shipment print: %s", e)
        return JSONResponse(
            {"success": False, "message": f"打印失败：{str(e)}"},
            status_code=500,
        )


@router.get("/api/shipment/download/{filename:path}")
def shipment_download(filename: str):
    from app.utils.path_io.path_utils import get_app_data_dir

    output_dir = os.path.join(get_app_data_dir(), "shipment_outputs")
    safe = os.path.basename(filename) or filename
    file_path = os.path.join(output_dir, safe)
    if file_path and os.path.exists(file_path):
        return FileResponse(
            file_path,
            filename=safe,
            media_type="application/octet-stream",
        )
    return JSONResponse(
        {"success": False, "message": "文件不存在"},
        status_code=404,
    )


@router.get("/api/shipment/orders/purchase-units")
def shipment_orders_purchase_units():
    units = _svc().get_purchase_units()
    return {"success": True, "data": units, "count": len(units)}


@router.post("/api/shipment/orders/clear-shipment")
def shipment_orders_clear_shipment(
    request: Request, payload: dict[str, Any] = Body(default_factory=dict)
):
    purchase_unit = str(payload.get("purchase_unit") or "").strip()
    if not purchase_unit:
        raise HTTPException(status_code=400, detail="缺少购买单位参数")
    result = _run_shipment_orders_agent(
        request=request,
        action="clear_shipment",
        params={"purchase_unit": purchase_unit},
        route_path="/api/shipment/orders/clear-shipment",
    )
    return JSONResponse(result, status_code=200 if result.get("success") else 500)


@router.get("/api/shipment/orders")
def shipment_orders_list(limit: int = Query(default=100, ge=1, le=5000)):
    orders_list = _svc().get_orders(limit=limit) or []
    inner = {"success": True, "data": orders_list, "count": len(orders_list)}
    return {"success": True, "data": inner, "count": len(inner)}


@router.get("/api/shipment/orders/search")
def shipment_orders_search(q: str = Query(default="")):
    qs = (q or "").strip()
    if not qs:
        return {"success": True, "data": [], "count": 0}
    rows = _svc().search_orders(qs)
    return {"success": True, "data": rows, "count": len(rows)}


@router.get("/api/shipment/orders/latest")
def shipment_orders_latest():
    orders = _svc().get_orders(limit=10) or []
    return {"success": True, "data": orders}


@router.post("/api/shipment/orders/set-sequence")
def shipment_orders_set_sequence(
    request: Request, payload: dict[str, Any] = Body(default_factory=dict)
):
    sequence = int(payload.get("sequence", 1))
    result = _run_shipment_orders_agent(
        request=request,
        action="set_sequence",
        params={"sequence": sequence},
        route_path="/api/shipment/orders/set-sequence",
    )
    return JSONResponse(result, status_code=200 if result.get("success") else 500)


@router.post("/api/shipment/orders/reset-sequence")
def shipment_orders_reset_sequence(request: Request):
    result = _run_shipment_orders_agent(
        request=request,
        action="reset_sequence",
        params={},
        route_path="/api/shipment/orders/reset-sequence",
    )
    return JSONResponse(result, status_code=200 if result.get("success") else 500)


@router.delete("/api/shipment/orders/clear-all")
def shipment_orders_clear_all(request: Request):
    result = _run_shipment_orders_agent(
        request=request,
        action="clear_all",
        params={},
        route_path="/api/shipment/orders/clear-all",
    )
    return JSONResponse(result, status_code=200 if result.get("success") else 500)


@router.get("/api/shipment/orders/{order_number}")
def shipment_orders_get(order_number: str):
    order = _svc().get_order(str(order_number))
    if order:
        return {"success": True, "data": order}
    raise HTTPException(status_code=404, detail="订单不存在")


_api_order_routes = importlib.import_module("app.fastapi_routes.shipment_api_order_routes")
api_orders_list = _api_order_routes.api_orders_list
api_orders_create = _api_order_routes.api_orders_create
api_orders_delete_root = _api_order_routes.api_orders_delete_root
api_orders_latest = _api_order_routes.api_orders_latest
api_orders_search = _api_order_routes.api_orders_search
api_orders_set_sequence = _api_order_routes.api_orders_set_sequence
api_orders_reset_sequence = _api_order_routes.api_orders_reset_sequence
api_orders_purchase_units = _api_order_routes.api_orders_purchase_units
api_orders_clear_shipment = _api_order_routes.api_orders_clear_shipment
api_orders_export = _api_order_routes.api_orders_export
api_orders_clear_all = _api_order_routes.api_orders_clear_all
api_orders_update = _api_order_routes.api_orders_update
api_orders_get = _api_order_routes.api_orders_get
shipment_orders_delete = _api_order_routes.shipment_orders_delete


# ----- /api/shipment/shipment-records -----


@router.get("/api/shipment/records")
def shipment_records_dashboard_alias(
    unit: str | None = Query(default=None),
    unit_name: str | None = Query(default=None),
    per_page: int = Query(default=100, ge=1, le=500),
    sort: str | None = Query(default=None),
):
    """企业客服等页面使用的短路径；与 shipment-records/records 同源，支持 per_page。"""
    _ = sort  # 预留与前端 sort=created_at_desc 对齐；列表默认按 created_at 倒序
    u = (unit or unit_name or "").strip() or None
    records = _svc().get_shipment_records(u, limit=per_page)
    return {"success": True, "data": records}


@router.get("/api/shipment/shipment-records/records")
@router.get("/api/shipment/shipment-records/records/", include_in_schema=False)
def shipment_records_list(
    unit: str | None = Query(default=None),
    unit_name: str | None = Query(default=None),
):
    try:
        from app.mod_sdk.erp_domain_dispatch import try_invoke_erp_domain_handler

        mod_out = try_invoke_erp_domain_handler(
            "shipment",
            "records_list",
            unit=unit,
            unit_name=unit_name,
        )
        if mod_out is not None:
            return mod_out
    except RECOVERABLE_ERRORS:
        logger.debug("erp domain shipment.records_list dispatch skipped", exc_info=True)
    u = (unit or unit_name or "").strip() or None
    records = _svc().get_shipment_records(u)
    return {"success": True, "data": records}


@router.post("/api/shipment/shipment-records/record")
def shipment_records_create(request: Request, payload: dict[str, Any] = Body(...)):
    """新建出货记录（从出货记录管理页手动建单）。"""
    unit_name = str(payload.get("unit_name") or payload.get("purchase_unit") or "").strip()
    if not unit_name:
        raise HTTPException(status_code=400, detail="缺少购买单位")
    products = payload.get("products") or []
    if not isinstance(products, list):
        products = []
    result = _run_shipment_records_agent(
        request=request,
        action="create",
        params={
            "unit_name": unit_name,
            "products": products,
            "contact_person": payload.get("contact_person"),
            "contact_phone": payload.get("contact_phone"),
        },
        route_path="/api/shipment/shipment-records/record",
    )
    return JSONResponse(result, status_code=200 if result.get("success") else 400)


@router.patch("/api/shipment/shipment-records/record")
def shipment_records_patch(request: Request, payload: dict[str, Any] = Body(...)):
    record_id = payload.get("id")
    if not record_id:
        raise HTTPException(status_code=400, detail="缺少记录 ID")
    result = _run_shipment_records_agent(
        request=request,
        action="update",
        params={
            "id": int(record_id),
            "unit_name": payload.get("unit_name"),
            "products": payload.get("products"),
            "date": payload.get("date"),
            **{
                k: v for k, v in payload.items() if k not in ("id", "unit_name", "products", "date")
            },
        },
        route_path="/api/shipment/shipment-records/record",
    )
    return JSONResponse(result, status_code=200 if result.get("success") else 404)


@router.delete("/api/shipment/shipment-records/record")
def shipment_records_delete(request: Request, payload: dict[str, Any] = Body(...)):
    record_id = payload.get("id")
    if not record_id:
        raise HTTPException(status_code=400, detail="缺少记录 ID")
    result = _run_shipment_records_agent(
        request=request,
        action="delete",
        params={"id": int(record_id)},
        route_path="/api/shipment/shipment-records/record",
    )
    return JSONResponse(result, status_code=200 if result.get("success") else 404)


@router.get("/api/shipment/shipment-records/export")
def shipment_records_export(
    unit: str | None = Query(default=None),
    unit_name: str | None = Query(default=None),
    template_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
):
    u = (unit or unit_name or "").strip() or None
    result = _svc().export_shipment_records(
        unit_name=u,
        template_id=template_id,
        status_filter=status,
    )
    fp = _safe_shipment_export_path(result)
    if result.get("success") and fp:
        return FileResponse(
            fp,
            filename=os.path.basename(fp),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    return JSONResponse(result, status_code=200 if result.get("success") else 500)
