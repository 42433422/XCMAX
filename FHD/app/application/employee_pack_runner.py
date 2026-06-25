"""employee_pack 工具执行（委托 employee_runtime.executor）。"""

from __future__ import annotations

from typing import Any

from app.mod_sdk.employee_tool_registry import execute_employee_tool, is_employee_tool


def execute_employee_pack_tool(
    tool_name: str,
    args: dict[str, Any] | str,
    workspace_root: str | None = None,
) -> str:
    return execute_employee_tool(tool_name, args, workspace_root)


def try_execute_employee_planner_tool(
    name: str,
    args: dict[str, Any] | str,
    workspace_root: str | None = None,
    *,
    db_write_token: str | None = None,
) -> str | None:
    _ = db_write_token
    if not is_employee_tool(name):
        return None
    return execute_employee_tool(name, args, workspace_root)


__all__ = ["execute_employee_pack_tool", "try_execute_employee_planner_tool"]
