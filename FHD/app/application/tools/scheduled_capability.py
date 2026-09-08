"""Create scheduled capabilities in the authenticated durable task center."""

from typing import Any

from app.application.agent_orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_control import run_operation_lock
from app.application.agent_orchestrator.unified_task import create_unified_task
from app.infrastructure.auth.agent_principal import (
    bind_agent_runtime_context,
    require_agent_principal,
)
from app.infrastructure.request_context import get_current_request


def create_scheduled_capability(args: dict[str, Any], resolved: dict[str, Any]) -> dict[str, Any]:
    request = get_current_request()
    if request is None:
        return {"success": False, "message": "创建定时任务需要有效登录会话"}
    principal = require_agent_principal(request)
    if "recurrence" in args:
        from app.application.agent_orchestrator.recurring_schedule_service import (
            RecurringScheduleService,
        )

        row = RecurringScheduleService().create({**args, **resolved}, principal)
        return {
            "success": True,
            "schedule_created": True,
            "operation_executed": False,
            "schedule_id": row["schedule_id"],
            "next_run_at": row["next_run_at"],
            "deduplicated": row["deduplicated"],
            "approval_policy": "each_occurrence",
            "message": "周期计划已保存，每次生成的任务须在任务中心审批；不自动累积未完成任务。",
        }
    task_id = str(args.get("task_id") or "").strip()
    if not task_id or not args.get("scheduled_at"):
        return {"success": False, "message": "定时任务必须提供 task_id 和带时区的 scheduled_at"}
    context = bind_agent_runtime_context({"source": "erp_agent_schedule"}, principal)
    with run_operation_lock(f"task:{principal.user_id}:{task_id}"):
        result = create_unified_task(
            orchestrator=AgentOrchestrator(),
            user_id=principal.user_id,
            task_id=task_id,
            title=f"定时执行 {resolved['tool_id']}.{resolved['action']}",
            message=str(args.get("message") or "定时执行已登记能力"),
            tool_id=resolved["tool_id"],
            action=resolved["action"],
            params=resolved["params"],
            runtime_context=context,
            scheduled_at=args["scheduled_at"],
        )
    return {
        "success": True,
        "task_created": True,
        "operation_executed": False,
        "pending_approval": result.run.status == "waiting_user",
        "task_id": task_id,
        "run_id": result.run.run_id,
        "status": result.run.status,
        "schedule": result.run.metadata.get("schedule"),
        "deduplicated": result.deduplicated,
        "message": "请在任务中心查看并审批；创建成功不代表业务已执行。",
    }


def schedule_management_definition() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "manage_erp_schedule",
            "description": "查询、暂停、恢复或取消当前账号的周期计划。控制后续触发；已生成任务需在任务中心单独控制。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "pause", "resume", "cancel"]},
                    "schedule_id": {
                        "type": "string",
                        "description": "先从 list 获取真实 ID，禁止编造。",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    }


def manage_schedule(args: dict[str, Any]) -> str:
    import json

    from fastapi import HTTPException

    from app.application.agent_orchestrator.schedule_repository import ScheduleRepository
    from app.utils.operational_errors import RECOVERABLE_ERRORS

    try:
        request = get_current_request()
        if request is None:
            raise ValueError("需要有效登录")
        principal = require_agent_principal(request)
        repository = ScheduleRepository()
        if args.get("action") == "list":
            rows = repository.list_owned(principal.user_id, principal.tenant_id)
            for row in rows:
                row.pop("lease_owner", None)
            return json.dumps({"success": True, "schedules": rows}, ensure_ascii=False)
        changed = repository.control(
            str(args.get("schedule_id") or ""),
            principal.user_id,
            principal.tenant_id,
            str(args.get("action") or ""),
        )
        return json.dumps(
            {"success": changed, "message": "控制仅影响后续触发；已生成任务保留。"},
            ensure_ascii=False,
        )
    except HTTPException:
        return json.dumps({"success": False, "message": "需要有效登录"}, ensure_ascii=False)
    except RECOVERABLE_ERRORS:
        return json.dumps({"success": False, "message": "调度控制失败"}, ensure_ascii=False)
