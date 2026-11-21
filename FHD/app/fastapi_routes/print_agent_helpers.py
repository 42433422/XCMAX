"""Print HTTP projection of the shared capability execution contract."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from app.fastapi_routes.tools_execute import run_tools_execute_agent


def run_print_agent(
    *,
    request: Request,
    action: str,
    params: dict[str, Any],
    route_path: str,
) -> tuple[dict[str, Any], int]:
    return run_tools_execute_agent(
        request=request,
        body={
            "tool_id": "print",
            "action": action,
            "params": params,
            "idempotency_key": params.get("idempotency_key"),
        },
        route_path=route_path,
    )
