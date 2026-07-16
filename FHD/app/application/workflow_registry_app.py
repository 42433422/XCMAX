"""Application seam for route-facing workflow registry operations.

The underlying registry remains patchable for tests and runtime integration,
while HTTP routes depend only on the application layer.
"""

from __future__ import annotations

from typing import Any


def get_workflow_tool_registry() -> dict[str, Any]:
    from app.services.tools_execution.registry import get_workflow_tool_registry as resolve

    return resolve()


def _normalize_action(action: str, params: dict[str, Any] | None = None) -> str:
    from app.services.tools_execution.registry import _normalize_action as normalize

    return normalize(action, params)


__all__ = ["_normalize_action", "get_workflow_tool_registry"]
