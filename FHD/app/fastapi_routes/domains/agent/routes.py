"""Agent run API for plan, execution, and state inspection."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse

from app.application.agent_orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.approval_grant import (
    ApprovalGrantError,
    consume_approval_grant,
    issue_approval_grant,
)
from app.application.agent_orchestrator.run_control import run_operation_lock
from app.application.agent_orchestrator.task_models import task_from_run, tenant_id_of_run
from app.application.agent_orchestrator.unified_task import (
    UnifiedTaskConflictError,
    UnifiedTaskError,
    create_unified_task,
    task_capabilities,
)
from app.infrastructure.auth.agent_principal import AgentPrincipal, require_agent_principal
from app.utils.json_safe import json_safe
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent"])

_PUBLIC_AGENT_ERROR = "Agent 执行失败，详细信息已记录"
_PUBLIC_AGENT_SERVICE_ERROR = "Agent 服务暂时不可用，请稍后重试"
_PUBLIC_APPROVAL_ERROR = "approval_grant 无效、过期或与当前步骤不匹配"
_INTERNAL_ERROR_KEYS = frozenset({"error", "exception", "stack_trace", "traceback"})


def _success(data: Any, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"success": True, "data": json_safe(data)}
    payload.update(extra)
    return payload


def _redact_internal_errors(value: Any) -> Any:
    """Remove persisted exception details before crossing the public API boundary."""
    if isinstance(value, dict):
        return {
            key: (
                _PUBLIC_AGENT_ERROR
                if str(key).lower() in _INTERNAL_ERROR_KEYS and child
                else _redact_internal_errors(child)
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_redact_internal_errors(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_internal_errors(item) for item in value]
    return value


def _public_run_dict(run: Any) -> dict[str, Any]:
    return _redact_internal_errors(run.to_dict())


def _public_event_dict(event: Any) -> dict[str, Any]:
    return _redact_internal_errors(event.to_dict())


def _internal_error_response(operation: str) -> JSONResponse:
    logger.exception("%s failed", operation)
    return JSONResponse(
        {"success": False, "message": _PUBLIC_AGENT_SERVICE_ERROR},
        status_code=500,
    )


def _run_response(run: Any, *, principal: AgentPrincipal) -> dict[str, Any]:
    approval = issue_approval_grant(run, principal_id=principal.user_id)
    public_run = _public_run_dict(run)
    extra: dict[str, Any] = {"capabilities": task_capabilities(run)}
    if approval:
        extra["approval"] = approval
    return _success(public_run, **extra)


def _run_reference_response(run: Any) -> dict[str, Any]:
    task_context = run.metadata.get("task_context")
    task_id = str(task_context.get("task_id") or "") if isinstance(task_context, dict) else ""
    return _success({"run_id": str(run.run_id), "status": str(run.status), "task_id": task_id})


def _task_envelope(
    orchestrator: AgentOrchestrator,
    task: Any,
    *,
    include_runs: bool = True,
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
    payload["runs"] = [_public_run_dict(run) for run in runs]
    payload["active_run"] = _public_run_dict(active) if active is not None else None
    payload["capabilities"] = task_capabilities(active) if active is not None else {}
    command = orchestrator.latest_task_control(active.run_id) if active is not None else None
    payload["control_command"] = command.to_dict() if command is not None else None
    return payload


def _owned_run(
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


@router.post("/api/agent/runs", response_model=None)
def create_agent_run(
    body: dict[str, Any] = Body(default_factory=dict),
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> dict[str, Any] | JSONResponse:
    data = body or {}
    message = str(data.get("message") or "").strip()
    if not message:
        return JSONResponse(
            {"success": False, "message": "message 不能为空"},
            status_code=400,
        )

    runtime_context_raw = data.get("runtime_context") or {}
    if not isinstance(runtime_context_raw, dict):
        return JSONResponse(
            {"success": False, "message": "runtime_context 必须是对象"},
            status_code=400,
        )
    runtime_context = dict(runtime_context_raw)
    if principal.tenant_id:
        runtime_context["tenant_id"] = principal.tenant_id

    try:
        run = AgentOrchestrator().start_run(
            user_id=principal.user_id,
            message=message,
            runtime_context=runtime_context,
            auto_execute=bool(data.get("auto_execute", True)),
        )
        status_code = 202 if run.status in {"waiting_user", "blocked"} else 200
        return JSONResponse(_run_response(run, principal=principal), status_code=status_code)
    except RECOVERABLE_ERRORS:
        return _internal_error_response("create agent run")


@router.get("/api/agent/runs", response_model=None)
def list_agent_runs(
    limit: int = Query(default=50, ge=1, le=200),
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> dict[str, Any] | JSONResponse:
    try:
        # Public callers can only enumerate their own runs. Cross-user admin search should
        # use a separately permissioned admin route, not a caller-controlled query string.
        runs = AgentOrchestrator().list_runs(user_id=principal.user_id, limit=limit)
        return _success([_public_run_dict(run) for run in runs], count=len(runs))
    except RECOVERABLE_ERRORS:
        return _internal_error_response("list agent runs")


@router.get("/api/agent/tasks", response_model=None)
def list_agent_tasks(
    limit: int = Query(default=50, ge=1, le=200),
    include_archived: bool = Query(default=False),
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> dict[str, Any] | JSONResponse:
    try:
        orchestrator = AgentOrchestrator()
        # Lazy, non-destructive backfill keeps pre-migration AgentRun history
        # visible without mutating the historical run payloads.
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
        return _success(
            [_task_envelope(orchestrator, task, include_runs=False) for task in tasks],
            count=len(tasks),
        )
    except RECOVERABLE_ERRORS:
        return _internal_error_response("list agent tasks")


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
        response = _run_response(result.run, principal=principal)
        response["deduplicated"] = result.deduplicated
        return JSONResponse(
            response, status_code=202 if result.run.status == "waiting_user" else 200
        )
    except UnifiedTaskConflictError as exc:
        return JSONResponse(
            {"success": False, "message": str(exc)},
            status_code=409,
        )
    except UnifiedTaskError as exc:
        return JSONResponse(
            {"success": False, "message": str(exc)},
            status_code=400,
        )
    except RECOVERABLE_ERRORS:
        return _internal_error_response("create agent task")


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
            return JSONResponse(
                {"success": False, "message": "任务不存在"},
                status_code=404,
            )
        return _success(_task_envelope(orchestrator, task))
    except RECOVERABLE_ERRORS:
        return _internal_error_response("get agent task")


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
            return JSONResponse(
                {"success": False, "message": "任务不存在"},
                status_code=404,
            )
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
        return _success(archived.to_dict() if archived is not None else owned.to_dict())
    except RECOVERABLE_ERRORS:
        return _internal_error_response("archive agent task")


@router.post("/api/agent/runs/observed-tool", response_model=None)
def record_observed_tool_run(
    body: dict[str, Any] = Body(default_factory=dict),
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> dict[str, Any] | JSONResponse:
    """Record a completed low-risk desktop fast path in the durable task ledger."""
    data = body or {}
    message = str(data.get("message") or "").strip()
    tool_id = str(data.get("tool_id") or "").strip()
    action = str(data.get("action") or "").strip()
    params = data.get("params") or {}
    output = data.get("output") or {}
    runtime_context_raw = data.get("runtime_context") or {}
    if not message or not isinstance(params, dict) or not isinstance(output, dict):
        return JSONResponse(
            {"success": False, "message": "message、params 与 output 格式无效"},
            status_code=400,
        )
    if not isinstance(runtime_context_raw, dict):
        return JSONResponse(
            {"success": False, "message": "runtime_context 必须是对象"},
            status_code=400,
        )
    runtime_context = dict(runtime_context_raw)
    if principal.tenant_id:
        runtime_context["tenant_id"] = principal.tenant_id

    from app.application.agent_orchestrator.observed_tool_trace import (
        create_observed_tool_trace_run,
    )
    from app.application.agent_orchestrator.tool_spec import validate_tool_call

    validation = validate_tool_call(tool_id, action, params)
    spec = validation.spec
    if not validation.ok or spec is None or spec.risk != "low" or not spec.idempotent:
        return JSONResponse(
            {"success": False, "message": "只允许记录已注册的低风险幂等工具"},
            status_code=400,
        )

    try:
        run = create_observed_tool_trace_run(
            spec=spec,
            user_id=principal.user_id,
            message=message,
            params=params,
            output=output,
            response=str(data.get("response") or output.get("message") or ""),
            runtime_context=runtime_context,
            source=str(data.get("source") or "desktop_fast_path"),
        )
        return _run_reference_response(run)
    except RECOVERABLE_ERRORS:
        return _internal_error_response("record observed tool run")


@router.get("/api/agent/runs/{run_id}", response_model=None)
def get_agent_run(
    run_id: str,
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> dict[str, Any] | JSONResponse:
    try:
        orchestrator = AgentOrchestrator()
        run, error = _owned_run(orchestrator, run_id, principal)
        if error is not None:
            return error
        response = _run_response(run, principal=principal)
        command = orchestrator.latest_task_control(run_id)
        if command is not None:
            response["control_command"] = command.to_dict()
        return response
    except RECOVERABLE_ERRORS:
        return _internal_error_response("get agent run")


@router.post("/api/agent/runs/{run_id}/continue", response_model=None)
def continue_agent_run(
    run_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> dict[str, Any] | JSONResponse:
    data = body or {}
    runtime_context = data.get("runtime_context") or {}
    if not isinstance(runtime_context, dict):
        return JSONResponse(
            {"success": False, "message": "runtime_context 必须是对象"},
            status_code=400,
        )
    try:
        with run_operation_lock(run_id):
            orchestrator = AgentOrchestrator()
            current, error = _owned_run(orchestrator, run_id, principal)
            if error is not None:
                return error
            claims = consume_approval_grant(
                str(data.get("approval_grant") or ""),
                run=current,
                principal_id=principal.user_id,
            )
            run = orchestrator.continue_run(
                run_id,
                approved_by=principal.user_id,
                approved_step_id=str(claims["step_id"]),
                runtime_context=runtime_context,
            )
        if run is None:
            return JSONResponse(
                {"success": False, "message": "agent run 不存在"},
                status_code=404,
            )
        status_code = 202 if run.status in {"waiting_user", "blocked"} else 200
        return JSONResponse(_run_response(run, principal=principal), status_code=status_code)
    except ApprovalGrantError:
        return JSONResponse(
            {"success": False, "message": _PUBLIC_APPROVAL_ERROR},
            status_code=403,
        )
    except RECOVERABLE_ERRORS:
        return _internal_error_response("continue agent run")


def _control_agent_run(
    run_id: str,
    *,
    action: str,
    principal: AgentPrincipal,
    runtime_context: dict[str, Any] | None = None,
) -> dict[str, Any] | JSONResponse:
    def apply_control() -> dict[str, Any] | JSONResponse:
        orchestrator = AgentOrchestrator()
        _, error = _owned_run(orchestrator, run_id, principal)
        if error is not None:
            return error
        if action == "pause":
            run = orchestrator.pause_run(run_id, requested_by=principal.user_id)
        elif action == "cancel":
            run = orchestrator.cancel_run(run_id, requested_by=principal.user_id)
        else:
            run = orchestrator.resume_run(
                run_id,
                requested_by=principal.user_id,
                runtime_context=runtime_context,
            )
        response = _run_response(run, principal=principal)
        command = orchestrator.latest_task_control(run_id)
        if command is not None:
            response["control_command"] = command.to_dict()
        return response

    # Pause/cancel must be able to persist their command while another worker is
    # executing the run. Resume remains serialized with approval/retry mutations.
    if action in {"pause", "cancel"}:
        return apply_control()
    with run_operation_lock(run_id):
        return apply_control()


@router.post("/api/agent/runs/{run_id}/pause", response_model=None)
def pause_agent_run(
    run_id: str,
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> dict[str, Any] | JSONResponse:
    return _control_agent_run(run_id, action="pause", principal=principal)


@router.post("/api/agent/runs/{run_id}/cancel", response_model=None)
def cancel_agent_run(
    run_id: str,
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> dict[str, Any] | JSONResponse:
    return _control_agent_run(run_id, action="cancel", principal=principal)


@router.post("/api/agent/runs/{run_id}/resume", response_model=None)
def resume_agent_run(
    run_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> dict[str, Any] | JSONResponse:
    runtime_context = (body or {}).get("runtime_context") or {}
    if not isinstance(runtime_context, dict):
        return JSONResponse(
            {"success": False, "message": "runtime_context 必须是对象"}, status_code=400
        )
    return _control_agent_run(
        run_id,
        action="resume",
        principal=principal,
        runtime_context=runtime_context,
    )


@router.post("/api/agent/runs/{run_id}/retry", response_model=None)
def retry_agent_run(
    run_id: str,
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> dict[str, Any] | JSONResponse:
    with run_operation_lock(run_id):
        orchestrator = AgentOrchestrator()
        run, error = _owned_run(orchestrator, run_id, principal)
        if error is not None:
            return error
        assert run is not None
        if run.status not in {"failed", "cancelled", "blocked"}:
            return JSONResponse(
                {"success": False, "message": "只有失败、取消或阻塞的任务可以重试"},
                status_code=409,
            )
        if run.metadata.get("non_retryable"):
            return JSONResponse(
                {"success": False, "message": "该观察记录不能作为执行任务重试"},
                status_code=409,
            )
        try:
            retried = orchestrator.retry_run(
                run_id,
                requested_by=principal.user_id,
            )
            return _run_reference_response(retried)
        except RECOVERABLE_ERRORS:
            return _internal_error_response("retry agent run")


@router.get("/api/agent/runs/{run_id}/events", response_model=None)
def list_agent_run_events(
    run_id: str,
    after_event_id: str | None = Query(default=None),
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> dict[str, Any] | JSONResponse:
    try:
        orchestrator = AgentOrchestrator()
        _, error = _owned_run(orchestrator, run_id, principal)
        if error is not None:
            return error
        events = orchestrator.list_events(run_id, after_event_id=after_event_id)
        return _success([_public_event_dict(event) for event in events], count=len(events))
    except RECOVERABLE_ERRORS:
        return _internal_error_response("list agent run events")


@router.get("/api/agent/runs/{run_id}/events/stream", response_model=None)
async def stream_agent_run_events(
    run_id: str,
    after_event_id: str | None = Query(default=None),
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> StreamingResponse | JSONResponse:
    orchestrator = AgentOrchestrator()
    _, error = _owned_run(orchestrator, run_id, principal)
    if error is not None:
        return error

    async def event_stream():
        cursor = after_event_id
        deadline = time.monotonic() + 60.0
        terminal = {"completed", "failed", "cancelled"}
        while time.monotonic() < deadline:
            current_orchestrator = AgentOrchestrator()
            events = current_orchestrator.list_events(run_id, after_event_id=cursor)
            for event in events:
                cursor = event.event_id
                yield f"id: {event.event_id}\nevent: {event.event_type}\ndata: {json.dumps(json_safe(_public_event_dict(event)), ensure_ascii=False)}\n\n"
            current = current_orchestrator.get_run(run_id)
            if current is None or (current.status in terminal and not events):
                break
            await asyncio.sleep(0.25)
        yield "event: stream.closed\ndata: {}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
