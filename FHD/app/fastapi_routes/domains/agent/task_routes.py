"""Durable task-center API routes separated from Agent run execution routes."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse

from app.application.agent_orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_control import run_operation_lock
from app.application.agent_orchestrator.task_dispatcher import get_agent_task_dispatcher
from app.application.agent_orchestrator.task_execution_repository import (
    get_task_execution_repository,
)
from app.application.agent_orchestrator.task_models import task_from_run, tenant_id_of_run
from app.application.agent_orchestrator.unified_task import (
    UnifiedTaskConflictError,
    UnifiedTaskError,
    create_unified_task,
    task_capabilities,
)
from app.fastapi_routes.domains.agent.route_support import (
    internal_error_response,
    public_run_dict,
    run_response,
    success,
)
from app.infrastructure.auth.agent_principal import AgentPrincipal, require_agent_principal
from app.utils.json_safe import json_safe
from app.utils.operational_errors import RECOVERABLE_ERRORS

router = APIRouter(tags=["agent"])


def _task_envelope(
    orchestrator: AgentOrchestrator,
    task: Any,
    *,
    include_runs: bool = True,
    executions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if include_runs:
        runs = [
            run
            for run in orchestrator.list_task_runs(user_id=task.user_id, task_id=task.task_id)
            if tenant_id_of_run(run) == task.tenant_id
        ]
        active = next((run for run in runs if run.run_id == task.active_run_id), None)
        active = active or (runs[-1] if runs else None)
    else:
        active = orchestrator.get_run(task.active_run_id) if task.active_run_id else None
        if (
            active is None
            or active.user_id != task.user_id
            or tenant_id_of_run(active) != task.tenant_id
        ):
            active = None
        runs = []
    payload = task.to_dict()
    payload["runs"] = [public_run_dict(run) for run in runs]
    payload["active_run"] = public_run_dict(active) if active is not None else None
    payload["capabilities"] = task_capabilities(active) if active is not None else {}
    command = orchestrator.latest_task_control(active.run_id) if active is not None else None
    payload["control_command"] = command.to_dict() if command is not None else None
    execution = None
    if active is not None:
        execution = (
            executions.get(active.run_id)
            if executions is not None
            else get_task_execution_repository().get(active.run_id)
        )
    payload["execution"] = execution.to_dict() if execution is not None else None
    return payload


def _execution_map(tasks: list[Any]) -> dict[str, Any]:
    run_ids = [str(task.active_run_id or "") for task in tasks if task.active_run_id]
    return get_task_execution_repository().list_for_run_ids(run_ids)


def _task_stream_envelope(task: Any, executions: dict[str, Any]) -> dict[str, Any]:
    payload = task.to_dict()
    execution = executions.get(str(task.active_run_id or ""))
    payload.update(
        {
            "runs": [],
            "active_run": None,
            "capabilities": {},
            "control_command": None,
            "execution": execution.to_dict() if execution is not None else None,
        }
    )
    return payload


@router.get("/api/agent/tasks", response_model=None)
def list_agent_tasks(
    limit: int = Query(default=50, ge=1, le=200),
    include_archived: bool = Query(default=False),
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> dict[str, Any] | JSONResponse:
    try:
        orchestrator = AgentOrchestrator()
        for run in orchestrator.list_runs(user_id=principal.user_id, limit=limit):
            if principal.tenant_id and tenant_id_of_run(run) != principal.tenant_id:
                continue
            context = run.metadata.get("task_context")
            task_id = str(context.get("task_id") or "") if isinstance(context, dict) else ""
            if not task_id:
                continue
            existing = orchestrator.get_task(
                user_id=principal.user_id,
                task_id=task_id,
                tenant_id=principal.tenant_id or None,
            )
            if existing is None:
                orchestrator.save_task(task_from_run(run))
        tasks = orchestrator.list_tasks(
            user_id=principal.user_id,
            tenant_id=principal.tenant_id or None,
            limit=limit,
            include_archived=include_archived,
        )
        executions = _execution_map(tasks)
        return success(
            [
                _task_envelope(
                    orchestrator,
                    task,
                    include_runs=False,
                    executions=executions,
                )
                for task in tasks
            ],
            count=len(tasks),
        )
    except RECOVERABLE_ERRORS:
        return internal_error_response("list agent tasks")


@router.get("/api/agent/task-runtime", response_model=None)
def get_agent_task_runtime(
    _principal: AgentPrincipal = Depends(require_agent_principal),
) -> dict[str, Any]:
    snapshot = get_agent_task_dispatcher().snapshot()
    return success(
        {
            "running": bool(snapshot["running"]),
            "max_workers": int(snapshot["max_workers"]),
            "active_count": int(snapshot["active_count"]),
        }
    )


@router.post("/api/agent/tasks", response_model=None)
def create_agent_task(
    body: dict[str, Any] = Body(default_factory=dict),
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> dict[str, Any] | JSONResponse:
    data = body or {}
    params = data.get("params") or {}
    runtime_context_raw = data.get("runtime_context") or {}
    if not isinstance(params, dict) or not isinstance(runtime_context_raw, dict):
        return JSONResponse(
            {"success": False, "message": "params 与 runtime_context 必须是对象"},
            status_code=400,
        )
    runtime_context = dict(runtime_context_raw)
    try:
        if principal.tenant_id:
            runtime_context["tenant_id"] = principal.tenant_id
        task_id = str(data.get("task_id") or "").strip()
        if not task_id or len(task_id) > 160 or "/" in task_id:
            return JSONResponse(
                {
                    "success": False,
                    "message": "task_id 不能为空、不能含 /，且长度不能超过 160",
                },
                status_code=400,
            )
        with run_operation_lock(f"task:{principal.user_id}:{task_id}"):
            result = create_unified_task(
                orchestrator=AgentOrchestrator(),
                user_id=principal.user_id,
                task_id=task_id,
                title=str(data.get("title") or ""),
                message=str(data.get("message") or data.get("title") or ""),
                tool_id=str(data.get("tool_id") or ""),
                action=str(data.get("action") or ""),
                params=params,
                runtime_context=runtime_context,
            )
        response = run_response(result.run, principal=principal)
        response["deduplicated"] = result.deduplicated
        return JSONResponse(
            response, status_code=202 if result.run.status == "waiting_user" else 200
        )
    except UnifiedTaskConflictError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=409)
    except UnifiedTaskError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=400)
    except RECOVERABLE_ERRORS:
        return internal_error_response("create agent task")


@router.get("/api/agent/tasks/events/stream", response_model=None)
async def stream_agent_tasks(
    once: bool = Query(default=False),
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> StreamingResponse:
    async def event_stream():
        previous = ""
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            orchestrator = AgentOrchestrator()
            tasks = orchestrator.list_tasks(
                user_id=principal.user_id,
                tenant_id=principal.tenant_id or None,
                limit=200,
                include_archived=False,
            )
            executions = _execution_map(tasks)
            snapshot = [_task_stream_envelope(task, executions) for task in tasks]
            encoded = json.dumps(json_safe(snapshot), ensure_ascii=False, sort_keys=True)
            if encoded != previous:
                previous = encoded
                yield f"event: task.snapshot\ndata: {encoded}\n\n"
            if once:
                break
            await asyncio.sleep(0.25)
        yield "event: stream.closed\ndata: {}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/agent/tasks/{task_id}", response_model=None)
def get_agent_task(
    task_id: str,
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> dict[str, Any] | JSONResponse:
    try:
        orchestrator = AgentOrchestrator()
        task = orchestrator.get_task(
            user_id=principal.user_id,
            task_id=task_id,
            tenant_id=principal.tenant_id or None,
        )
        if task is None:
            return JSONResponse({"success": False, "message": "任务不存在"}, status_code=404)
        return success(_task_envelope(orchestrator, task))
    except RECOVERABLE_ERRORS:
        return internal_error_response("get agent task")


@router.post("/api/agent/tasks/{task_id}/archive", response_model=None)
def archive_agent_task(
    task_id: str,
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> dict[str, Any] | JSONResponse:
    try:
        orchestrator = AgentOrchestrator()
        owned = orchestrator.get_task(
            user_id=principal.user_id,
            task_id=task_id,
            tenant_id=principal.tenant_id or None,
        )
        if owned is None:
            return JSONResponse({"success": False, "message": "任务不存在"}, status_code=404)
        if owned.status not in {"completed", "failed", "cancelled"}:
            return JSONResponse(
                {"success": False, "message": "只有终态任务可以归档"},
                status_code=409,
            )
        archived = orchestrator.archive_task(
            user_id=principal.user_id,
            task_id=task_id,
            tenant_id=principal.tenant_id or None,
        )
        return success(archived.to_dict() if archived is not None else owned.to_dict())
    except RECOVERABLE_ERRORS:
        return internal_error_response("archive agent task")


__all__ = ["router"]
