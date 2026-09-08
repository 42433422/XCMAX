"""Account-owned recurring schedule controls; occurrences use normal task approval."""

from typing import Any

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from app.application.agent_orchestrator.recurring_schedule_service import RecurringScheduleService
from app.fastapi_routes.domains.agent.route_support import internal_error_response, success
from app.infrastructure.auth.agent_principal import AgentPrincipal, require_agent_principal
from app.utils.operational_errors import RECOVERABLE_ERRORS

router = APIRouter(tags=["agent"])


@router.post("/api/agent/schedules", response_model=None)
def create_schedule(
    body: dict[str, Any] = Body(default_factory=dict),
    principal: AgentPrincipal = Depends(require_agent_principal),
):
    try:
        row = RecurringScheduleService().create(body, principal)
        row.pop("lease_owner", None)
        return success(row)
    except (ValueError, KeyError):
        return JSONResponse(
            {"success": False, "message": "周期任务参数或请求 ID 无效"}, status_code=400
        )
    except RECOVERABLE_ERRORS:
        return internal_error_response("create recurring schedule")


@router.get("/api/agent/schedules", response_model=None)
def list_schedules(principal: AgentPrincipal = Depends(require_agent_principal)):
    try:
        rows = RecurringScheduleService().repository.list_owned(
            principal.user_id, principal.tenant_id
        )
        for row in rows:
            row.pop("lease_owner", None)
        return success(rows)
    except RECOVERABLE_ERRORS:
        return internal_error_response("list recurring schedules")


@router.post("/api/agent/schedules/{schedule_id}/{action}", response_model=None)
def control_schedule(
    schedule_id: str, action: str, principal: AgentPrincipal = Depends(require_agent_principal)
):
    try:
        changed = RecurringScheduleService().repository.control(
            schedule_id, principal.user_id, principal.tenant_id, action
        )
        if not changed:
            return JSONResponse(
                {"success": False, "message": "调度不存在或已取消"}, status_code=404
            )
        return success(
            {
                "schedule_id": schedule_id,
                "action": action,
                "message": "控制影响后续触发；已生成的任务请在任务中心单独暂停或取消。",
            }
        )
    except ValueError:
        return JSONResponse({"success": False, "message": "无效调度操作"}, status_code=400)
    except RECOVERABLE_ERRORS:
        return internal_error_response("control recurring schedule")
