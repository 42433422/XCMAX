# -*- coding: utf-8 -*-
"""Legacy shim：委托 employee_tool_registry + employee_runtime.executor。"""

from __future__ import annotations

import json
from typing import Any

from app.mod_sdk.employee_tool_registry import (
    build_employee_tools_status,
    execute_employee_tool,
    invalidate_employee_tool_cache,
    is_employee_tool,
    pack_id_to_legacy_tool_name,
    resolve_tool_to_pack_id,
)


def pack_id_to_tool_name(pack_id: str) -> str:
    return pack_id_to_legacy_tool_name(pack_id)


def tool_name_to_pack_id(tool_name: str) -> str | None:
    return resolve_tool_to_pack_id(tool_name)


def pack_has_runtime(pack_id: str) -> bool:
    from app.application.employee_runtime.loader import pack_has_direct_python_runtime, resolve_pack_dir

    pdir = resolve_pack_dir(pack_id)
    return pack_has_direct_python_runtime(pdir) if pdir else False


def invalidate_employee_planner_registry() -> None:
    invalidate_employee_tool_cache()


def load_employee_planner_tool_extensions() -> list[dict[str, Any]]:
    from app.mod_sdk.employee_tool_registry import build_employee_pack_tool_definitions

    return build_employee_pack_tool_definitions()


def is_employee_planner_tool(name: str) -> bool:
    return is_employee_tool(name)


def build_employee_planner_status() -> dict[str, Any]:
    return build_employee_tools_status()


__all__ = [
    "build_employee_planner_status",
    "invalidate_employee_planner_registry",
    "is_employee_planner_tool",
    "load_employee_planner_tool_extensions",
    "pack_has_runtime",
    "pack_id_to_tool_name",
    "tool_name_to_pack_id",
]
