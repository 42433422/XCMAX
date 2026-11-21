"""Shared AgentOrchestrator bridge for shipment compatibility routes."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from app.application.agent_orchestrator.trace_payloads import agent_node_output as agent_node_output


def _run_shipment_agent(
    *,
    request: Request,
    tool_id: str,
    action: str,
    params: dict[str, Any],
    route_path: str,
    default_risk: str,
) -> dict[str, Any]:
    from app.fastapi_routes.tools_execute import run_tools_execute_agent

    payload, _ = run_tools_execute_agent(
        request=request,
        body={"tool_id": tool_id, "action": action, "params": dict(params)},
        route_path=route_path,
    )
    return payload


def run_shipment_records_agent(
    *, request: Request, action: str, params: dict[str, Any], route_path: str
) -> dict[str, Any]:
    return _run_shipment_agent(
        request=request,
        tool_id="shipment_records",
        action=action,
        params=params,
        route_path=route_path,
        default_risk="medium",
    )


def run_shipment_orders_agent(
    *, request: Request, action: str, params: dict[str, Any], route_path: str
) -> dict[str, Any]:
    return _run_shipment_agent(
        request=request,
        tool_id="shipment_orders",
        action=action,
        params=params,
        route_path=route_path,
        default_risk="high",
    )
