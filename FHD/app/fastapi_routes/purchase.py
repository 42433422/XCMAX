"""
采购管理 API 路由

来源：从 legacy_inventory.py 中 /api/purchase/* 端点迁出。
读取端点复用 inventory facade 暴露的 PurchaseService；写入端点通过统一能力入口
进入 purchase.* ToolSpecV2 工具后再调用同一服务，不再保留平行 ``*_v2`` 应用服务。

覆盖：
- /api/purchase/suppliers*    供应商 CRUD
- /api/purchase/orders*       采购订单 CRUD + 审批/取消
- /api/purchase/inbounds*     采购入库单 CRUD
- /api/purchase/summary       采购汇总
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse

from app.fastapi_routes.tools_execute import run_tools_execute_agent

logger = logging.getLogger(__name__)

router = APIRouter(tags=["purchase"])


def _svc():
    from app.application.facades.inventory_facade import PurchaseService

    return PurchaseService()


def _run_purchase_agent(
    *,
    request: Request,
    action: str,
    params: dict[str, Any],
    route_path: str,
) -> JSONResponse:
    result, status = run_tools_execute_agent(
        request=request,
        body={"tool_id": "purchase", "action": action, "params": params},
        route_path=route_path,
    )
    return JSONResponse(result, status_code=status)


# ──────────────────────────── 供应商 ────────────────────────────


@router.get("/api/purchase/suppliers")
def purchase_suppliers(
    status: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
):
    return _svc().get_suppliers(status=status, keyword=keyword)


@router.get("/api/purchase/suppliers/summary")
def purchase_suppliers_summary():
    return _svc().get_supplier_summary()


@router.get("/api/purchase/suppliers/{supplier_id}")
def purchase_supplier_get(supplier_id: int):
    return _svc().get_supplier(supplier_id)


@router.post("/api/purchase/suppliers")
def purchase_suppliers_post(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    return _run_purchase_agent(
        request=request,
        action="create_supplier",
        params=dict(body or {}),
        route_path="/api/purchase/suppliers",
    )


@router.put("/api/purchase/suppliers/{supplier_id}")
def purchase_suppliers_put(
    request: Request,
    supplier_id: int,
    body: dict[str, Any] = Body(default_factory=dict),
):
    return _run_purchase_agent(
        request=request,
        action="update_supplier",
        params={"supplier_id": supplier_id, **dict(body or {})},
        route_path="/api/purchase/suppliers/{supplier_id}",
    )


@router.delete("/api/purchase/suppliers/{supplier_id}")
def purchase_supplier_delete(request: Request, supplier_id: int):
    return _run_purchase_agent(
        request=request,
        action="delete_supplier",
        params={"supplier_id": supplier_id},
        route_path="/api/purchase/suppliers/{supplier_id}",
    )


# ──────────────────────────── 采购订单 ────────────────────────────


@router.get("/api/purchase/orders")
def purchase_orders(
    supplier_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    page: int = Query(default=1),
    per_page: int = Query(default=20),
):
    start_dt = datetime.fromisoformat(start_date) if start_date else None
    end_dt = datetime.fromisoformat(end_date) if end_date else None
    return _svc().get_purchase_orders(
        supplier_id=supplier_id,
        status=status,
        start_date=start_dt,
        end_date=end_dt,
        page=page,
        per_page=per_page,
    )


@router.get("/api/purchase/orders/{order_id}")
def purchase_order_get(order_id: int):
    return _svc().get_purchase_order(order_id)


@router.post("/api/purchase/orders")
def purchase_orders_post(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    return _run_purchase_agent(
        request=request,
        action="create_order",
        params=dict(body or {}),
        route_path="/api/purchase/orders",
    )


@router.put("/api/purchase/orders/{order_id}")
def purchase_orders_put(
    request: Request,
    order_id: int,
    body: dict[str, Any] = Body(default_factory=dict),
):
    return _run_purchase_agent(
        request=request,
        action="update_order",
        params={"order_id": order_id, **dict(body or {})},
        route_path="/api/purchase/orders/{order_id}",
    )


@router.post("/api/purchase/orders/{order_id}/approve")
def purchase_orders_approve(
    request: Request,
    order_id: int,
    approver: str = Query(default="system"),
):
    return _run_purchase_agent(
        request=request,
        action="approve_order",
        params={"order_id": order_id, "approver": approver},
        route_path="/api/purchase/orders/{order_id}/approve",
    )


@router.post("/api/purchase/orders/{order_id}/cancel")
def purchase_orders_cancel(request: Request, order_id: int):
    return _run_purchase_agent(
        request=request,
        action="cancel_order",
        params={"order_id": order_id},
        route_path="/api/purchase/orders/{order_id}/cancel",
    )


# ──────────────────────────── 采购入库 ────────────────────────────


@router.get("/api/purchase/inbounds")
def purchase_inbounds(
    supplier_id: int | None = Query(default=None),
    order_id: int | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    page: int = Query(default=1),
    per_page: int = Query(default=20),
):
    start_dt = datetime.fromisoformat(start_date) if start_date else None
    end_dt = datetime.fromisoformat(end_date) if end_date else None
    return _svc().get_purchase_inbounds(
        supplier_id=supplier_id,
        order_id=order_id,
        start_date=start_dt,
        end_date=end_dt,
        page=page,
        per_page=per_page,
    )


@router.post("/api/purchase/inbounds")
def purchase_inbounds_post(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    return _run_purchase_agent(
        request=request,
        action="create_inbound",
        params=dict(body or {}),
        route_path="/api/purchase/inbounds",
    )


# ──────────────────────────── 汇总 ────────────────────────────


@router.get("/api/purchase/summary")
def purchase_summary():
    return _svc().get_purchase_summary()
