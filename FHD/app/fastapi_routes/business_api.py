"""FHD 业务能力 HTTP 出口：通过神经域 emit / NeuroBus publish 触发既有流水线。

供 MODstore 员工或其它内网客户端调用。若设置环境变量 ``FHD_BUSINESS_API_KEY``，
则须在请求头携带 ``X-FHD-Business-Key``；未设置时仅依赖现有 LAN 门禁（生产务必配置密钥）。"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/business", tags=["business-bridge"])


def _expected_business_key() -> str:
    return (os.environ.get("FHD_BUSINESS_API_KEY") or "").strip()


def require_fhd_business_key(
    x_fhd_business_key: Annotated[str | None, Header(alias="X-FHD-Business-Key")] = None,
) -> None:
    exp = _expected_business_key()
    if not exp:
        return
    got = (x_fhd_business_key or "").strip()
    if got != exp:
        raise HTTPException(status_code=401, detail="invalid X-FHD-Business-Key")


BusinessKeyDep = Annotated[None, Depends(require_fhd_business_key)]


class PrintLabelBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    job_id: str | None = None
    document_name: str = "document"
    printer_id: str = "default"
    copies: int = 1


@router.post("/print/label")
async def business_print_label(
    request: Request,
    body: PrintLabelBody,
    _: BusinessKeyDep,
) -> dict[str, Any]:
    run = _run_business_event_agent(
        request=request,
        action="print_label",
        params=body.model_dump(),
        route_path="/api/business/print/label",
    )
    return _agent_node_output(run, "business_event_print_label")


class InventoryUpdateBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    product_id: str
    warehouse_id: str = "default"
    delta: int = 0
    reason: str = "api_business"
    new_quantity: int = 0


@router.post("/inventory/update")
async def business_inventory_update(
    request: Request,
    body: InventoryUpdateBody,
    _: BusinessKeyDep,
) -> dict[str, Any]:
    run = _run_business_event_agent(
        request=request,
        action="inventory_update",
        params=body.model_dump(),
        route_path="/api/business/inventory/update",
    )
    return _agent_node_output(run, "business_event_inventory_update")


class OcrRecognizeBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    request_id: str | None = None
    image_url: str
    ocr_type: str = "general"
    user_id: str = "system"


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


def _business_agent_user_id(request: Request, payload: dict[str, Any]) -> str:
    return str(
        request.headers.get("X-User-Id")
        or request.headers.get("X-User-ID")
        or payload.get("user_id")
        or payload.get("userId")
        or "business-api"
    ).strip()


def _run_business_event_agent(
    *,
    request: Request,
    action: str,
    params: dict[str, Any],
    route_path: str,
) -> Any:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode
    from app.services.tools_execution.registry import get_workflow_tool_registry

    registry = get_workflow_tool_registry()
    action_meta = dict((registry.get("business_event") or {}).get("actions") or {}).get(action)
    if not isinstance(action_meta, dict):
        raise HTTPException(status_code=400, detail=f"unregistered business event action: {action}")

    node_id = f"business_event_{action}"
    user_id = _business_agent_user_id(request, params)
    plan = PlanGraph(
        plan_id=node_id,
        intent=node_id,
        todo_steps=[f"通过 AgentOrchestrator 发布业务事件 business_event.{action}"],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id="business_event",
                action=action,
                params=dict(params or {}),
                risk=str(action_meta.get("risk") or "high"),
                idempotent=bool(action_meta.get("idempotent", False)),
                description=f"Publish business event {action} through the unified Agent runtime.",
            )
        ],
        risk_level=str(action_meta.get("risk") or "high"),
        metadata={"source": "business_api", "route": route_path},
    )
    runtime_context = {
        "source": "business_api",
        "route": route_path,
        "request_path": str(request.url.path),
        "user_id": user_id,
        "route_confirmed": True,
    }
    orchestrator = AgentOrchestrator()
    run = orchestrator.start_run_from_plan(
        user_id=user_id,
        message=f"Business event: {action}",
        plan=plan,
        runtime_context=runtime_context,
    )
    if run.status == "waiting_user":
        continued = orchestrator.continue_run(
            run.run_id,
            approved_by=user_id or "business-api",
            runtime_context=runtime_context,
        )
        if continued is not None:
            run = continued
    return run


def _run_business_ocr_request_agent(
    *,
    request: Request,
    request_id: str,
    image_url: str,
    ocr_type: str,
    user_id: str,
) -> Any:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode

    plan = PlanGraph(
        plan_id="business_ocr_request",
        intent="business_ocr_request",
        todo_steps=["通过 AgentOrchestrator 发布业务 OCR 请求"],
        nodes=[
            WorkflowNode(
                node_id="business_ocr_request",
                tool_id="ocr",
                action="request",
                params={
                    "request_id": request_id,
                    "image_url": image_url,
                    "ocr_type": ocr_type,
                    "user_id": user_id,
                },
                risk="low",
                idempotent=True,
                description="Publish a business OCR request through the unified Agent runtime.",
            )
        ],
        risk_level="low",
        metadata={"source": "business_api", "route": "/api/business/ocr/recognize"},
    )
    return AgentOrchestrator().start_run_from_plan(
        user_id=user_id,
        message=f"Business OCR request: {image_url}",
        plan=plan,
        runtime_context={
            "source": "business_api",
            "request_path": str(request.url.path),
            "request_id": request_id,
            "user_id": user_id,
        },
    )


@router.post("/ocr/recognize")
async def business_ocr_recognize(
    request: Request,
    body: OcrRecognizeBody,
    _: BusinessKeyDep,
) -> dict[str, Any]:
    rid = (body.request_id or "").strip() or str(uuid.uuid4())
    user_id = body.user_id.strip() or "system"
    run = _run_business_ocr_request_agent(
        request=request,
        request_id=rid,
        image_url=body.image_url.strip(),
        ocr_type=(body.ocr_type or "general").strip(),
        user_id=user_id,
    )
    return _agent_node_output(run, "business_ocr_request")


class ShipmentCreateBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    unit_name: str
    items: list[dict[str, Any]] = Field(default_factory=list)
    contact_person: str = ""
    contact_phone: str = ""


@router.post("/shipment/create")
async def business_shipment_create(
    request: Request,
    body: ShipmentCreateBody,
    _: BusinessKeyDep,
) -> dict[str, Any]:
    payload = {
        "unit_name": body.unit_name.strip(),
        "items": body.items,
        "contact_person": body.contact_person.strip(),
        "contact_phone": body.contact_phone.strip(),
    }
    run = _run_business_event_agent(
        request=request,
        action="shipment_create",
        params=payload,
        route_path="/api/business/shipment/create",
    )
    return _agent_node_output(run, "business_event_shipment_create")


@router.get("/health")
async def business_health(_: BusinessKeyDep) -> dict[str, Any]:
    return {"success": True, "business_api": "up", "key_required": bool(_expected_business_key())}
