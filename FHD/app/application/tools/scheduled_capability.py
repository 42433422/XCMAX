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
