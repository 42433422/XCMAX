"""Agent run API for plan, execution, and state inspection."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse

from app.application.agent_orchestrator import AgentOrchestrator
from app.utils.json_safe import json_safe
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent"])


def _success(data: Any, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"success": True, "data": json_safe(data)}
    payload.update(extra)
    return payload


@router.post("/api/agent/runs", response_model=None)
def create_agent_run(
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any] | JSONResponse:
    data = body or {}
    message = str(data.get("message") or "").strip()
    if not message:
        return JSONResponse(
            {"success": False, "message": "message 不能为空"},
            status_code=400,
        )

    user_id = str(data.get("user_id") or "default")
    runtime_context = data.get("runtime_context") or {}
    if not isinstance(runtime_context, dict):
        return JSONResponse(
            {"success": False, "message": "runtime_context 必须是对象"},
            status_code=400,
        )

    try:
        run = AgentOrchestrator().start_run(
            user_id=user_id,
            message=message,
            runtime_context=runtime_context,
            auto_execute=bool(data.get("auto_execute", True)),
        )
        status_code = 202 if run.status in {"waiting_user", "blocked"} else 200
        return JSONResponse(_success(run.to_dict()), status_code=status_code)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("create agent run failed: %s", exc)
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@router.get("/api/agent/runs", response_model=None)
def list_agent_runs(
    user_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any] | JSONResponse:
    try:
        runs = AgentOrchestrator().list_runs(user_id=user_id, limit=limit)
        return _success([run.to_dict() for run in runs], count=len(runs))
    except RECOVERABLE_ERRORS as exc:
        logger.exception("list agent runs failed: %s", exc)
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@router.get("/api/agent/runs/{run_id}", response_model=None)
def get_agent_run(run_id: str) -> dict[str, Any] | JSONResponse:
    try:
        run = AgentOrchestrator().get_run(run_id)
        if run is None:
            return JSONResponse(
                {"success": False, "message": "agent run 不存在"},
                status_code=404,
            )
        return _success(run.to_dict())
    except RECOVERABLE_ERRORS as exc:
        logger.exception("get agent run failed: %s", exc)
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@router.post("/api/agent/runs/{run_id}/continue", response_model=None)
def continue_agent_run(
    run_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any] | JSONResponse:
    data = body or {}
    runtime_context = data.get("runtime_context") or {}
    if not isinstance(runtime_context, dict):
        return JSONResponse(
            {"success": False, "message": "runtime_context 必须是对象"},
            status_code=400,
        )
    try:
        run = AgentOrchestrator().continue_run(
            run_id,
            approved_by=str(data.get("approved_by") or ""),
            approved_step_id=str(data.get("step_id") or data.get("node_id") or ""),
            runtime_context=runtime_context,
        )
        if run is None:
            return JSONResponse(
                {"success": False, "message": "agent run 不存在"},
                status_code=404,
            )
        status_code = 202 if run.status in {"waiting_user", "blocked"} else 200
        return JSONResponse(_success(run.to_dict()), status_code=status_code)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("continue agent run failed: %s", exc)
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@router.get("/api/agent/runs/{run_id}/events", response_model=None)
def list_agent_run_events(
    run_id: str,
    after_event_id: str | None = Query(default=None),
) -> dict[str, Any] | JSONResponse:
    try:
        orchestrator = AgentOrchestrator()
        if orchestrator.get_run(run_id) is None:
            return JSONResponse(
                {"success": False, "message": "agent run 不存在"},
                status_code=404,
            )
        events = orchestrator.list_events(run_id, after_event_id=after_event_id)
        return _success([event.to_dict() for event in events], count=len(events))
    except RECOVERABLE_ERRORS as exc:
        logger.exception("list agent run events failed: %s", exc)
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
