"""Shared public response and ownership helpers for Agent API routers."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, cast

from fastapi.responses import JSONResponse

from app.application.agent_orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.approval_grant import issue_approval_grant
from app.application.agent_orchestrator.task_dispatcher import notify_agent_task_dispatcher
from app.application.agent_orchestrator.task_execution_repository import (
    get_task_execution_repository,
)
from app.application.agent_orchestrator.unified_task import (
    run_owned_by as run_owned_by,
)
from app.application.agent_orchestrator.unified_task import (
    scoped_tasks as scoped_tasks,
)
from app.application.agent_orchestrator.unified_task import task_capabilities
from app.application.agent_orchestrator.unified_task import (
    task_scope_matches as task_scope_matches,
)
from app.infrastructure.auth.agent_principal import AgentPrincipal
from app.utils.json_safe import json_safe

logger = logging.getLogger(__name__)

PUBLIC_AGENT_ERROR = "Agent 执行失败，详细信息已记录"
PUBLIC_AGENT_SERVICE_ERROR = "Agent 服务暂时不可用，请稍后重试"
PUBLIC_APPROVAL_ERROR = "approval_grant 无效、过期或与当前步骤不匹配"
_INTERNAL_ERROR_KEYS = frozenset({"error", "exception", "stack_trace", "traceback"})


def without_runtime_identity(raw: dict[str, Any]) -> dict[str, Any]:
    """Discard caller identity fields before resolving any server principal."""
    context = dict(raw)
    for key in (
        "workspace_root",
        "node_outputs",
        "active_skills",
        "tenant_id",
        "user_id",
        "actor_id",
        "local_user_id",
        "authenticated_local_user_id",
        "_mod_authorization",
        "_actor_authorization",
        "_credential_authorization",
        "_tool_approval_scope",
        "_bulk_preview_scope",
        "_bulk_preview_scopes",
        "mutation_policy",
        "service_source",
        "template_base_dir",
        "route_module",
        "mod_id",
        "active_mod_id",
        "authenticated_username",
        "authenticated_display_name",
        "_dataset_access_context_trusted",
        "dataset_access_context",
    ):
        context.pop(key, None)
    return context


def authenticated_runtime_context(raw: dict[str, Any], principal: AgentPrincipal) -> dict[str, Any]:
    from app.infrastructure.workspace import workspace_root

    context = without_runtime_identity(raw)
    context["workspace_root"] = str(workspace_root())
    if context.get("source") == "admin_employee_workspace":
        if not principal.is_admin:
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail="员工管理工作空间仅限管理员")
        # This surface reports the actual host workspace, never a caller-supplied
        # display path masquerading as an isolated checkout or cloud machine.
        for key in ("worktree_path", "cwd", "workspace_path", "workspace_isolation"):
            context.pop(key, None)
        context["workspace_path"] = context["workspace_root"]
        context["workspace_isolation"] = "host_workspace"
    context.update(user_id=principal.user_id, actor_id=principal.user_id)
    if principal.tenant_id:
        context["tenant_id"] = principal.tenant_id
    if principal.mod_authorization:
        context["_mod_authorization"] = dict(principal.mod_authorization)
        context["mod_id"] = str(principal.mod_authorization["mod_id"])
    if principal.actor_authorization:
        context["_actor_authorization"] = dict(principal.actor_authorization)
    return context


def request_runtime_context(request: Any, raw: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.infrastructure.auth.agent_principal import require_agent_principal

    return authenticated_runtime_context(
        dict(raw or {}), require_agent_principal(request, x_user_id=None)
    )


def success(data: Any, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"success": True, "data": json_safe(data)}
    payload.update(extra)
    return payload


def redact_internal_errors(value: Any) -> Any:
    """Remove persisted exception details before crossing the public API boundary."""
    if isinstance(value, dict):
        return {
            key: (
                PUBLIC_AGENT_ERROR
                if str(key).lower() in _INTERNAL_ERROR_KEYS and child
                else redact_internal_errors(child)
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact_internal_errors(item) for item in value]
    if isinstance(value, tuple):
        return [redact_internal_errors(item) for item in value]
    return value


def public_run_dict(run: Any, *, read_run: Callable[[str], Any] | None = None) -> dict[str, Any]:
    # to_dict shares metadata with the stored run: redact only the recursive copy.
    data = cast("dict[str, Any]", redact_internal_errors(run.to_dict()))
    if isinstance(data.get("metadata"), dict):
        data["metadata"].pop("_tool_approval_grants", None)
        context = data["metadata"].get("runtime_context")
        if isinstance(context, dict):
            for key in ("_actor_authorization", "_mod_authorization", "_credential_authorization"):
                context.pop(key, None)
        if data["metadata"].get("child_results"):
            from app.application.agent_orchestrator.run_audit_scope import project_child_results
            from app.application.agent_orchestrator.run_repository import get_agent_run_repository

            data["metadata"]["child_results"] = redact_internal_errors(
                project_child_results(
                    run, read_run or (lambda run_id: get_agent_run_repository().get(run_id))
                )
            )
    return data


def public_event_dict(event: Any) -> dict[str, Any]:
    return cast("dict[str, Any]", redact_internal_errors(event.to_dict()))


def internal_error_response(operation: str) -> JSONResponse:
    logger.exception("%s failed", operation)
    return JSONResponse(
        {"success": False, "message": PUBLIC_AGENT_SERVICE_ERROR},
        status_code=500,
    )


def run_response(
    run: Any, *, principal: AgentPrincipal, read_run: Callable[[str], Any] | None = None
) -> dict[str, Any]:
    approval = issue_approval_grant(run, principal_id=principal.user_id)
    extra: dict[str, Any] = {"capabilities": task_capabilities(run)}
    if approval:
        extra["approval"] = approval
    execution = get_task_execution_repository().get(run.run_id)
    if execution is not None:
        extra["execution"] = execution.to_dict()
    return success(public_run_dict(run, read_run=read_run), **extra)


def run_reference_response(run: Any) -> dict[str, Any]:
    task_context = run.metadata.get("task_context")
    task_id = str(task_context.get("task_id") or "") if isinstance(task_context, dict) else ""
    return success({"run_id": str(run.run_id), "status": str(run.status), "task_id": task_id})


def owned_run(
    orchestrator: AgentOrchestrator,
    run_id: str,
    principal: AgentPrincipal,
) -> tuple[Any | None, JSONResponse | None]:
    run = orchestrator.get_run(run_id)
    if run is None:
        return None, JSONResponse(
            {"success": False, "message": "agent run 不存在"}, status_code=404
        )
    if not run_owned_by(run, principal):
        return None, JSONResponse(
            {"success": False, "message": "无权访问该 agent run"}, status_code=403
        )
    return run, None


def enqueue_run(run: Any, *, requested_by: str) -> None:
    get_task_execution_repository().enqueue(run, requested_by=requested_by)
    notify_agent_task_dispatcher()


def sync_execution_terminal_state(run: Any) -> None:
    state = {
        "paused": "paused",
        "blocked": "blocked",
        "completed": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
    }.get(str(run.status or ""))
    if state:
        get_task_execution_repository().transition(run.run_id, state)


__all__ = [
    "PUBLIC_APPROVAL_ERROR",
    "enqueue_run",
    "internal_error_response",
    "owned_run",
    "public_event_dict",
    "public_run_dict",
    "run_reference_response",
    "run_response",
    "success",
    "sync_execution_terminal_state",
]
