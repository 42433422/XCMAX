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
    return _success(public_run, approval=approval) if approval else _success(public_run)


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

    runtime_context = data.get("runtime_context") or {}
    if not isinstance(runtime_context, dict):
        return JSONResponse(
            {"success": False, "message": "runtime_context 必须是对象"},
            status_code=400,
        )

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


@router.get("/api/agent/runs/{run_id}", response_model=None)
def get_agent_run(
    run_id: str,
    principal: AgentPrincipal = Depends(require_agent_principal),
) -> dict[str, Any] | JSONResponse:
    try:
        run, error = _owned_run(AgentOrchestrator(), run_id, principal)
        if error is not None:
            return error
        return _run_response(run, principal=principal)
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
    with run_operation_lock(run_id):
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
        return _run_response(run, principal=principal)


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
