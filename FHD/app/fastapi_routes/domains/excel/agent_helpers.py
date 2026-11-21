"""Unified Agent-run helpers used by the legacy Excel route facade."""

from __future__ import annotations

import logging
from typing import Any, TypeVar, cast

from fastapi import Request

from app.application.agent_orchestrator.trace_payloads import (
    agent_node_output as agent_node_payload,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
PayloadT = TypeVar("PayloadT")


def trace_excel_route(
    payload: PayloadT,
    *,
    route: str,
    message: str,
    user_id: str = "",
    intent: str = "excel_ai_route",
    runtime_context: dict[str, Any] | None = None,
) -> PayloadT:
    if not isinstance(payload, dict) or payload.get("run_id") or payload.get("agent_run_id"):
        return payload
    try:
        from app.application.agent_orchestrator.chat_trace import create_chat_trace_run

        run = create_chat_trace_run(
            payload,
            message=message,
            runtime_context={
                "route": route,
                "source": "legacy_excel_route",
                **(runtime_context or {}),
            },
            user_id=user_id or "legacy-excel-route",
            source="legacy_excel_route",
            channel="excel_ai_route",
            intent=intent,
        )
    except RECOVERABLE_ERRORS:
        logger.exception("failed to attach AgentRun trace to excel route response")
        return payload
    traced = dict(payload)
    traced["run_id"] = run.run_id
    traced["agent_run_id"] = run.run_id
    return cast(PayloadT, traced)


def user_id_from_excel_skill_request(request: Request, body: dict[str, Any]) -> str:
    from app.fastapi_routes.tools_execute import user_id_from_tool_request

    return user_id_from_tool_request(request, body)


def run_excel_skill_agent(
    *,
    request: Request,
    body: dict[str, Any],
    route_path: str,
    tool_id: str,
    action: str,
    params: dict[str, Any],
    intent: str,
    message: str,
) -> dict[str, Any]:
    from app.fastapi_routes.tools_execute import run_tools_execute_agent

    payload, _ = run_tools_execute_agent(
        request=request,
        body={
            "tool_id": tool_id,
            "action": action,
            "params": dict(params),
            **{key: body[key] for key in ("request_id", "idempotency_key") if key in body},
        },
        route_path=route_path,
    )
    return payload


__all__ = [
    "agent_node_payload",
    "run_excel_skill_agent",
    "trace_excel_route",
    "user_id_from_excel_skill_request",
]
