"""Agent-runtime adapter for Memory v2 HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.application.agent_orchestrator.trace_payloads import agent_node_output as agent_output

__all__ = ["agent_output", "run_memory_v2_agent", "user_id_from_request"]


def user_id_from_request(request: Request, params: dict[str, Any]) -> str:
    from app.infrastructure.auth.dependencies import get_logged_in_user

    user = get_logged_in_user(request)
    owner = str(user.id)
    aliases = {owner}
    # A numeric legacy username may be another account's canonical id.
    if not str(user.username).isdecimal():
        aliases.add(str(user.username))
    claims = [
        str(value).strip()
        for value in (request.headers.get("X-User-Id"), params.get("user_id"), params.get("userId"))
        if value is not None and str(value).strip() not in {"", "default"}
    ]
    if any(value not in aliases for value in claims):
        raise HTTPException(status_code=403, detail="只能访问当前账户的记忆")
    from app.application.agent_task_context import scoped_personal_memory_id
    from app.fastapi_routes.domains.agent.route_support import authenticated_runtime_context
    from app.infrastructure.auth.agent_principal import require_agent_principal

    principal = require_agent_principal(request)
    return scoped_personal_memory_id(authenticated_runtime_context({}, principal))


def run_memory_v2_agent(
    *,
    request: Request,
    action: str,
    params: dict[str, Any],
    route_path: str,
    failure_status: int,
) -> JSONResponse:
    from app.fastapi_routes.tools_execute import run_tools_execute_agent

    data = dict(params)
    user_id_from_request(request, data)
    for key in ("user_id", "userId"):
        data.pop(key, None)
    payload, status = run_tools_execute_agent(
        request=request,
        body={"tool_id": "memory_v2", "action": action, "params": data},
        route_path=route_path,
    )
    return JSONResponse(payload, status_code=status)
