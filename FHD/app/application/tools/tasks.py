"""Account-scoped task observations through the existing task and execution stores."""

from __future__ import annotations

from typing import Any

from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_repository import get_agent_run_repository
from app.application.agent_orchestrator.task_execution_models import _task_id_of
from app.application.agent_orchestrator.task_execution_repository import (
    get_task_execution_repository,
)
from app.application.agent_orchestrator.tool_permission import actor_tool_denial
from app.application.agent_orchestrator.tool_spec import validate_tool_call
from app.application.agent_orchestrator.unified_task import (
    run_owned_by,
    scoped_tasks,
    task_scope_matches,
)
from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError, _bound_actor
from app.infrastructure.auth.agent_principal import AgentPrincipal
from app.utils.operational_errors import RECOVERABLE_ERRORS


def _task_row(task: Any, orchestrator: AgentOrchestrator, executions: dict, principal) -> dict:
    payload = task.to_dict()
    # Whitelist the observation; task/run metadata may contain sealed grants or
    # business arguments and is never part of this model-facing read contract.
    row = {
        key: payload[key]
        for key in (
            "task_id",
            "title",
            "status",
            "attention_state",
            "approval_required",
            "root_run_id",
            "attempt",
            "archived_at",
            "created_at",
            "updated_at",
        )
    }
    row["progress"] = {
        key: value
        for key, value in payload["progress"].items()
        if key in {"percent", "completed_units", "settled_units", "total_units", "indeterminate"}
        and isinstance(value, (int, bool))
    }
    active = orchestrator.get_run(task.active_run_id) if task.active_run_id else None
    active = (
        active
        if active is not None
        and run_owned_by(active, principal)
        and _task_id_of(active) == task.task_id
        else None
    )
    row["run_id"] = active.run_id if active is not None else ""
    execution = executions.get(row["run_id"])
    row["execution"] = (
        {
            key: value
            for key, value in execution.to_dict().items()
            if key in {"state", "execution_count", "last_error_code", "updated_at", "finished_at"}
        }
        if execution is not None
        and (execution.task_id, execution.user_id, execution.tenant_id)
        == (task.task_id, principal.user_id, principal.tenant_id)
        else None
    )
    if active is not None:
        from app.application.agent_orchestrator.verification_recovery import verification_report

        report = verification_report(active)
        row["result_verification"] = {key: report[key] for key in ("status", "accepted")}
    return row


def query_tasks(action: str, params: dict, context: dict) -> dict:
    validation = validate_tool_call("tasks", action, params)
    if not validation.ok:
        return {
            "success": False,
            "error_code": validation.error_code,
            "message": validation.message,
        }
    try:
        denial = actor_tool_denial("tasks", action, context, params)
        if denial is not None:
            return denial
        actor = _bound_actor(context)
        principal = AgentPrincipal(
            user_id=str(actor.id),
            tenant_id=str(context["tenant_id"]),
            mod_authorization=context.get("_mod_authorization"),
        )
        orchestrator = AgentOrchestrator(repository=get_agent_run_repository())
        if params.get("task_id"):
            task = orchestrator.get_task(
                user_id=principal.user_id,
                tenant_id=principal.tenant_id,
                task_id=params["task_id"],
            )
            if task is None or not task_scope_matches(orchestrator, task, principal):
                return {"success": False, "error_code": "task_not_found", "data": [], "count": 0}
            tasks = [task]
        else:
            tasks = scoped_tasks(
                orchestrator,
                principal=principal,
                limit=int(params.get("limit", 50)),
                include_archived=params.get("include_archived") is True,
            )
        executions = get_task_execution_repository().list_for_run_ids(
            [task.active_run_id for task in tasks if task.active_run_id]
        )
        rows = [_task_row(task, orchestrator, executions, principal) for task in tasks]
        return {"success": True, "data": rows, "count": len(rows)}
    except AgentModAuthorizationError:
        return {"success": False, "error_code": "task_read_not_authorized", "data": [], "count": 0}
    except RECOVERABLE_ERRORS:
        return {"success": False, "error_code": "task_read_unavailable", "data": [], "count": 0}
