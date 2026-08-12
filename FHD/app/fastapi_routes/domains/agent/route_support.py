"""Shared public response and ownership helpers for Agent API routers."""

from __future__ import annotations

import logging
from typing import Any

from fastapi.responses import JSONResponse

from app.application.agent_orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.approval_grant import issue_approval_grant
from app.application.agent_orchestrator.task_dispatcher import notify_agent_task_dispatcher
from app.application.agent_orchestrator.task_execution_repository import (
    get_task_execution_repository,
)
from app.application.agent_orchestrator.unified_task import task_capabilities
from app.infrastructure.auth.agent_principal import AgentPrincipal
from app.utils.json_safe import json_safe

logger = logging.getLogger(__name__)

PUBLIC_AGENT_ERROR = "Agent 执行失败，详细信息已记录"
PUBLIC_AGENT_SERVICE_ERROR = "Agent 服务暂时不可用，请稍后重试"
PUBLIC_APPROVAL_ERROR = "approval_grant 无效、过期或与当前步骤不匹配"
_INTERNAL_ERROR_KEYS = frozenset({"error", "exception", "stack_trace", "traceback"})


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


def public_run_dict(run: Any) -> dict[str, Any]:
    return redact_internal_errors(run.to_dict())


def public_event_dict(event: Any) -> dict[str, Any]:
    return redact_internal_errors(event.to_dict())


def internal_error_response(operation: str) -> JSONResponse:
    logger.exception("%s failed", operation)
    return JSONResponse(
        {"success": False, "message": PUBLIC_AGENT_SERVICE_ERROR},
        status_code=500,
    )


def run_response(run: Any, *, principal: AgentPrincipal) -> dict[str, Any]:
    approval = issue_approval_grant(run, principal_id=principal.user_id)
    extra: dict[str, Any] = {"capabilities": task_capabilities(run)}
    if approval:
        extra["approval"] = approval
    execution = get_task_execution_repository().get(run.run_id)
    if execution is not None:
        extra["execution"] = execution.to_dict()
    return success(public_run_dict(run), **extra)


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
    if not principal.is_admin and run.user_id != principal.user_id:
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
