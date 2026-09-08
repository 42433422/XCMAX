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
        from app.application.agent_orchestrator.schedule_authorization import ScheduleAuthorizations

        repository = RecurringScheduleService().repository
        rows = repository.list_owned(principal.user_id, principal.tenant_id)
        authorizations = ScheduleAuthorizations(repository).list_active(principal)
        for row in rows:
            row.pop("lease_owner", None)
            row["authorization"] = authorizations.get(row["schedule_id"])
        return success(rows)
    except RECOVERABLE_ERRORS:
        return internal_error_response("list recurring schedules")


@router.get("/api/agent/schedules/{schedule_id}/authorization", response_model=None)
def inspect_schedule_authorization(
    schedule_id: str, principal: AgentPrincipal = Depends(require_agent_principal)
):
    from app.application.agent_orchestrator.schedule_authorization import ScheduleAuthorizations

    try:
        return success(ScheduleAuthorizations().inspect(schedule_id, principal))
    except ValueError:
        return JSONResponse(
            {"success": False, "message": "计划不存在或操作已变化"}, status_code=404
        )
    except RECOVERABLE_ERRORS:
        return internal_error_response("inspect schedule authorization")


@router.post("/api/agent/schedules/{schedule_id}/authorization", response_model=None)
def authorize_schedule(
    schedule_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    principal: AgentPrincipal = Depends(require_agent_principal),
):
    from app.application.agent_orchestrator.schedule_authorization import ScheduleAuthorizations

    try:
        expires_at, max_runs = body.get("expires_at"), body.get("max_runs")
        if not isinstance(expires_at, str) or type(max_runs) is not int:
            raise ValueError("必须提供授权到期时间和次数")
        authorization = ScheduleAuthorizations().grant(
            schedule_id,
            principal,
            expires_at=expires_at,
            max_runs=max_runs,
            expected_scope_hash=str(body.get("scope_hash") or ""),
        )
        RecurringScheduleService().activate_pending(schedule_id, principal)
        return success(authorization)
    except ValueError:
        return JSONResponse(
            {"success": False, "message": "授权范围、到期时间或次数无效，请重新查看计划"},
            status_code=400,
        )
    except RECOVERABLE_ERRORS:
        return internal_error_response("authorize recurring schedule")


@router.delete("/api/agent/schedules/{schedule_id}/authorization", response_model=None)
def revoke_schedule_authorization(
    schedule_id: str, principal: AgentPrincipal = Depends(require_agent_principal)
):
    from app.application.agent_orchestrator.schedule_authorization import ScheduleAuthorizations

    try:
        return success({"revoked": ScheduleAuthorizations().revoke(schedule_id, principal)})
    except RECOVERABLE_ERRORS:
        return internal_error_response("revoke recurring schedule authorization")


@router.post("/api/agent/schedules/{schedule_id}/{action}", response_model=None)
def control_schedule(
    schedule_id: str, action: str, principal: AgentPrincipal = Depends(require_agent_principal)
):
    try:
        changed = RecurringScheduleService().control(schedule_id, principal, action)
        if not changed:
            return JSONResponse(
                {"success": False, "message": "调度不存在或已取消"}, status_code=404
            )
        return success(
            {
                "schedule_id": schedule_id,
                "action": action,
                "message": "暂停或取消也阻止未开始的自动任务；已开始的任务请在工作区查看和控制。",
            }
        )
    except ValueError:
        return JSONResponse({"success": False, "message": "无效调度操作"}, status_code=400)
    except RECOVERABLE_ERRORS:
        return internal_error_response("control recurring schedule")
