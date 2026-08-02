"""Application boundary for Memory v2 routes and agent workflow metadata."""

from __future__ import annotations

from typing import Any


def get_user_memory_service() -> Any:
    from app.services.user_memory_service import get_user_memory_service as _get_service

    return _get_service()


def get_memory_v2_action_meta(action: str) -> dict[str, Any] | None:
    from app.services.tools_execution.registry import get_workflow_tool_registry

    registry = get_workflow_tool_registry()
    value = dict((registry.get("memory_v2") or {}).get("actions") or {}).get(action)
    return value if isinstance(value, dict) else None
