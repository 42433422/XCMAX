"""employee_pack 工具执行（委托 employee_runtime.executor）。"""

from __future__ import annotations

from typing import Any

from app.mod_sdk import employee_tool_registry


def execute_employee_pack_tool(
    tool_name: str,
    args: dict[str, Any] | str,
    workspace_root: str | None = None,
    *,
    runtime_context: dict[str, Any] | None = None,
) -> str:
    return employee_tool_registry.execute_employee_tool(
        tool_name, args, workspace_root, runtime_context=runtime_context
    )


def try_execute_employee_planner_tool(
    name: str,
    args: dict[str, Any] | str,
    workspace_root: str | None = None,
    *,
    db_write_token: str | None = None,
    runtime_context: dict[str, Any] | None = None,
) -> str | None:
    _ = db_write_token
    if not employee_tool_registry.is_employee_tool(name):
        return None
    return employee_tool_registry.execute_employee_tool(
        name, args, workspace_root, runtime_context=runtime_context
    )


__all__ = ["execute_employee_pack_tool", "try_execute_employee_planner_tool"]
