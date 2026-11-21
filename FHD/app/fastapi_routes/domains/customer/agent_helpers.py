"""Customer HTTP adapters for the canonical authenticated execution entry."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from app.application.agent_orchestrator.trace_payloads import agent_node_output as agent_node_output
from app.fastapi_routes.tools_execute import user_id_from_tool_request as customers_agent_user_id

__all__ = ["agent_node_output", "customers_agent_user_id", "run_customers_agent"]


def run_customers_agent(
    *, request: Request, action: str, params: dict[str, Any], route_path: str
) -> tuple[dict[str, Any], int]:
    from app.fastapi_routes.tools_execute import run_tools_execute_agent

    return run_tools_execute_agent(
        request=request,
        body={"tool_id": "customers", "action": action, "params": dict(params)},
        route_path=route_path,
    )
