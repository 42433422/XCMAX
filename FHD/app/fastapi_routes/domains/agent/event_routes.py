"""Authenticated Agent event history and streaming endpoints."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse

from app.application.agent_orchestrator import AgentOrchestrator
from app.fastapi_routes.domains.agent.route_support import (
    internal_error_response as _internal_error_response,
)
from app.fastapi_routes.domains.agent.route_support import (
    owned_run as _owned_run,
)
from app.fastapi_routes.domains.agent.route_support import (
    public_event_dict as _public_event_dict,
)
from app.fastapi_routes.domains.agent.route_support import (
    success as _success,
)
from app.fastapi_routes.domains.agent.task_routes import router
from app.infrastructure.auth.agent_principal import AgentPrincipal, require_agent_principal
from app.utils.json_safe import json_safe
from app.utils.operational_errors import RECOVERABLE_ERRORS


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
