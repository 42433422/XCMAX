"""
采购管理 API 路由

来源：从 legacy_inventory.py 中 /api/purchase/* 端点迁出。
读取端点复用 inventory facade 暴露的 PurchaseService；写入端点通过 AgentOrchestrator
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

from app.application.workflow.workflow_types import normalize_workflow_risk
from app.domain.task_lifecycle.results import agent_node_output as _agent_node_output

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
) -> dict[str, Any]:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
    from app.application.workflow_registry_app import get_workflow_tool_registry
    from app.fastapi_routes.domains.agent.route_support import request_runtime_context

    registry = get_workflow_tool_registry()
    action_meta = dict((registry.get("purchase") or {}).get("actions") or {}).get(action)
    if not isinstance(action_meta, dict):
        return {
            "success": False,
            "message": f"未注册的 purchase 动作: {action}",
            "agent_status": "failed",
        }

    params = {key: value for key, value in params.items() if key not in {"tenant_id", "tenantId"}}
    node_id = f"purchase_{action}"
    runtime_context = request_runtime_context(
        request,
        {
            "source": "purchase_route",
            "route": route_path,
            "request_path": str(request.url.path),
            "route_confirmed": True,
            "service_source": "fastapi_purchase_route",
        },
    )
    user_id = str(runtime_context["user_id"])
    plan = PlanGraph(
        plan_id=node_id,
        intent=node_id,
        todo_steps=[f"通过 AgentOrchestrator 执行 purchase.{action}"],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id="purchase",
                action=action,
                params=dict(params or {}),
                risk=normalize_workflow_risk(str(action_meta.get("risk") or "medium")),
                idempotent=bool(action_meta.get("idempotent", False)),
                description=f"Execute purchase.{action} through the unified Agent runtime.",
            )
        ],
        risk_level=normalize_workflow_risk(str(action_meta.get("risk") or "medium")),
        metadata={"source": "purchase_route", "route": route_path},
    )
    orchestrator = AgentOrchestrator()
    run = orchestrator.start_run_from_plan(
        user_id=user_id,
        message=str(params.get("message") or f"Purchase {action}"),
        plan=plan,
        runtime_context=runtime_context,
    )
    if run.status in {"waiting_user", "running"}:
        continued = orchestrator.continue_run(
            run.run_id,
            approved_by=user_id,
            approved_step_id=node_id,
            runtime_context=runtime_context,
        )
        if continued is not None:
            run = continued
    return _agent_node_output(run, node_id)


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
