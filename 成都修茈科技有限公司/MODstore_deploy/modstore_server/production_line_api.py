"""双线全流程 API：制作线 + 运营线 + 五线状态，触发、审批、状态查询。"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/production-line", tags=["admin-production-line"])


class PipelineRunRequest(BaseModel):
    line: str = "production"
    start_from: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


class StepApprovalRequest(BaseModel):
    admin_user_id: int = 0


class StepRejectionRequest(BaseModel):
    admin_user_id: int = 0
    reason: str = ""


@router.get("/five-line-status")
async def api_five_line_status():
    from modstore_server.production_line_orchestrator import get_five_line_status

    return {"ok": True, "data": get_five_line_status()}


@router.get("/status")
async def api_pipeline_status():
    from modstore_server.production_line_orchestrator import get_production_line_status

    return {"ok": True, "data": get_production_line_status()}


@router.post("/run")
async def api_pipeline_run(body: PipelineRunRequest = PipelineRunRequest()):
    from modstore_server.production_line_orchestrator import run_production_line

    result = await run_production_line(
        line=body.line,
        start_from=body.start_from,
        context=body.context or {},
    )
    return {"ok": True, "data": result}


@router.post("/steps/{step_id}/approve")
async def api_step_approve(step_id: str, body: StepApprovalRequest = StepApprovalRequest()):
    from modstore_server.production_line_orchestrator import approve_production_line_step

    result = await approve_production_line_step(step_id, admin_user_id=body.admin_user_id)
    return {"ok": True, "data": {"step_id": result.step_id, "status": result.status.value}}


@router.post("/steps/{step_id}/reject")
async def api_step_reject(step_id: str, body: StepRejectionRequest = StepRejectionRequest()):
    from modstore_server.production_line_orchestrator import reject_production_line_step

    result = await reject_production_line_step(
        step_id, admin_user_id=body.admin_user_id, reason=body.reason
    )
    return {"ok": True, "data": {"step_id": result.step_id, "status": result.status.value}}


@router.post("/stop")
async def api_pipeline_stop():
    from modstore_server.production_line_orchestrator import get_production_line_orchestrator

    orch = get_production_line_orchestrator()
    orch.stop_pipeline()
    return {"ok": True, "message": "流水线已停止"}


@router.get("/operations-health")
async def api_operations_health():
    """运营线逐步健康度（优先拉 FHD，失败则仅返回 orchestrator 摘要）。"""
    import os

    import httpx

    fhd = (
        os.environ.get("XCAGI_FHD_INTERNAL_URL") or os.environ.get("FHD_INTERNAL_URL") or ""
    ).rstrip("/")
    if fhd:
        try:
            resp = httpx.get(f"{fhd}/api/operations-line/health", timeout=8.0)
            if resp.status_code < 400:
                data = resp.json()
                if isinstance(data, dict) and data.get("success"):
                    return {"ok": True, "source": "fhd", "data": data.get("data")}
        except Exception:
            logger.debug("FHD operations-health fetch failed", exc_info=True)
    from modstore_server.production_line_orchestrator import get_production_line_status

    return {"ok": True, "source": "orchestrator", "data": get_production_line_status()}


@router.post("/event")
async def api_operations_event(body: Dict[str, Any]):
    """接收 FHD operations_line_bridge 事件 → 六线事件轨路由（可选 secret）。"""
    from modstore_server.six_line_event_router import handle_operations_line_event

    routed = handle_operations_line_event(body if isinstance(body, dict) else {})
    logger.info(
        "production-line event: step=%s routed=%s",
        body.get("step_id"),
        routed.get("routed"),
    )
    return {"ok": True, "received": body.get("step_id"), "routing": routed}


@router.get("/event-rail/status")
async def api_event_rail_status():
    """事件轨状态：路由表条数、digest backlog 积压。"""
    from modstore_server.six_line_event_router import get_event_rail_status

    return {"ok": True, "data": get_event_rail_status()}


@router.get("/time-rail/graph")
async def api_time_rail_graph():
    """时间轨机器可读 workflow 图（节点 + 边 + phase）。"""
    from modstore_server.time_rail_workflow import graph_api_payload

    return graph_api_payload()


@router.get("/time-rail/status")
async def api_time_rail_status(node_id: Optional[str] = None):
    """时间轨节点 runtime：last_run / ok / guard_active。"""
    from modstore_server.time_rail_workflow import collect_node_runtime_status

    ids = [node_id.strip()] if node_id and node_id.strip() else None
    data = collect_node_runtime_status(node_ids=ids)
    return {"ok": True, "data": data}


@router.post("/webhook-outbox/process")
async def api_webhook_outbox_process(limit: int = 20):
    from modstore_server.cs_webhook_outbox import process_pending_outbox

    return {"ok": True, "data": process_pending_outbox(limit=limit)}


@router.post("/webhook-outbox/replay/{landing_contact_id}")
async def api_webhook_replay(landing_contact_id: int):
    from modstore_server.cs_webhook_outbox import replay_by_landing_contact_id

    return {"ok": True, "data": replay_by_landing_contact_id(int(landing_contact_id))}


@router.get("/steps")
async def api_pipeline_steps(line: str = "production"):
    from modstore_server.production_line_orchestrator import (
        OPERATIONS_LINE_STEPS,
        PRODUCTION_LINE_STEPS,
        get_production_line_orchestrator,
    )

    orch = get_production_line_orchestrator()
    steps_list = PRODUCTION_LINE_STEPS if line == "production" else OPERATIONS_LINE_STEPS
    steps = []
    for s in steps_list:
        status = orch.get_step_status(s.step_id)
        steps.append(
            {
                "step_id": s.step_id,
                "name": s.name,
                "description": s.description,
                "employee_ids": s.employee_ids,
                "sub_steps": s.sub_steps,
                "approval_gate": s.approval_gate.value,
                "auto_trigger_next": s.auto_trigger_next,
                "cross_line_trigger": s.cross_line_trigger,
                "status": status.value,
            }
        )
    return {"ok": True, "data": steps, "line": line}
