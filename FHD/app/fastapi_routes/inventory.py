"""
库存管理 API 路由 — HTTP 薄层，委托 InventoryAppService。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Query, Request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["inventory"])


def _svc():
    from app.application.inventory_app_service import InventoryAppService

    return InventoryAppService()


def _agent_node_output(run: Any, node_id: str) -> dict[str, Any]:
    final_output = getattr(run, "final_output", None)
    node_outputs = dict((final_output or {}).get("node_outputs") or {})
    output = dict(node_outputs.get(node_id) or {})
    if not output:
        for step in getattr(run, "steps", []) or []:
            if str(getattr(step, "node_id", "")) == node_id:
                output = dict(getattr(step, "output", {}) or {})
                break
    if not output:
        output = {"success": getattr(run, "status", "") == "completed"}
    if not output.get("success") and getattr(run, "error", "") and not output.get("message"):
        output["message"] = getattr(run, "error", "")
    run_id = str(getattr(run, "run_id", "") or "")
    if run_id:
        output["run_id"] = run_id
        output["agent_run_id"] = run_id
    output["agent_status"] = str(getattr(run, "status", "") or "")
    return output


def _inventory_agent_user_id(request: Request, payload: dict[str, Any]) -> str:
    return str(
        request.headers.get("X-User-Id")
        or request.headers.get("X-User-ID")
        or payload.get("user_id")
        or payload.get("userId")
        or "inventory-route"
    ).strip()


def _run_inventory_agent(
    *,
    request: Request,
    action: str,
    params: dict[str, Any],
    route_path: str,
) -> dict[str, Any]:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode
    from app.services.tools_execution.registry import get_workflow_tool_registry

    registry = get_workflow_tool_registry()
    action_meta = dict((registry.get("inventory") or {}).get("actions") or {}).get(action)
    if not isinstance(action_meta, dict):
        return {
            "success": False,
            "message": f"未注册的 inventory 动作: {action}",
            "agent_status": "failed",
        }

    node_id = f"inventory_{action}"
    user_id = _inventory_agent_user_id(request, params)
    plan = PlanGraph(
        plan_id=node_id,
        intent=node_id,
        todo_steps=[f"通过 AgentOrchestrator 执行 inventory.{action}"],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id="inventory",
                action=action,
                params=dict(params or {}),
                risk=str(action_meta.get("risk") or "medium"),
                idempotent=bool(action_meta.get("idempotent", False)),
                description=f"Execute inventory.{action} through the unified Agent runtime.",
            )
        ],
        risk_level=str(action_meta.get("risk") or "medium"),
        metadata={"source": "inventory_route", "route": route_path},
    )
    runtime_context = {
        "source": "inventory_route",
        "route": route_path,
        "request_path": str(request.url.path),
        "user_id": user_id,
        "route_confirmed": True,
        "service_source": "fastapi_inventory_route",
    }
    orchestrator = AgentOrchestrator()
    run = orchestrator.start_run_from_plan(
        user_id=user_id,
        message=str(params.get("message") or f"Inventory {action}"),
        plan=plan,
        runtime_context=runtime_context,
    )
    if run.status == "waiting_user":
        continued = orchestrator.continue_run(
            run.run_id,
            approved_by=user_id or "inventory-route",
            runtime_context=runtime_context,
        )
        if continued is not None:
            run = continued
    return _agent_node_output(run, node_id)


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


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
            "batch_no": data.get("batch_no"),
            "location_id": data.get("location_id"),
            "unit_price": _float_or_none(data.get("unit_price")),
            "reference_type": data.get("reference_type"),
            "reference_id": data.get("reference_id"),
            "operator": data.get("operator"),
            "remark": data.get("remark"),
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
            "batch_no": data.get("batch_no"),
            "location_id": data.get("location_id"),
            "unit_price": _float_or_none(data.get("unit_price")),
            "reference_type": data.get("reference_type"),
            "reference_id": data.get("reference_id"),
            "operator": data.get("operator"),
            "remark": data.get("remark"),
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
            "batch_no": data.get("batch_no"),
            "from_location_id": data.get("from_location_id"),
            "to_location_id": data.get("to_location_id"),
            "operator": data.get("operator"),
            "remark": data.get("remark"),
        },
        route_path="/api/inventory/transfer",
    )
