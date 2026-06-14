# -*- coding: utf-8 -*-
"""已安装 employee_pack → OpenAI function 工具注册表（Planner / workflow 合并）。"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from typing import Any

from app.application.employee_runtime.loader import (
    list_installed_pack_records,
    manifest_actions_handlers,
    pack_has_direct_python_runtime,
    parse_employee_config_v2,
    resolve_pack_dir,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_LEGACY_PREFIX = "employee__"
_LEGACY_SUFFIX = "__run"


def pack_id_to_legacy_tool_name(pack_id: str) -> str:
    pid = str(pack_id or "").strip()
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", pid.replace("-", "_"))
    return f"{_LEGACY_PREFIX}{safe}{_LEGACY_SUFFIX}"


def _tool_description(manifest: dict[str, Any], pack_id: str) -> str:
    name = str(manifest.get("name") or pack_id).strip()
    desc = str(manifest.get("description") or "").strip()
    emp = manifest.get("employee") if isinstance(manifest.get("employee"), dict) else {}
    label = str(emp.get("label") or "").strip()
    cfg = parse_employee_config_v2(manifest)
    cog = cfg.get("cognition") if isinstance(cfg.get("cognition"), dict) else {}
    agent = cog.get("agent") if isinstance(cog.get("agent"), dict) else {}
    prompt = str(agent.get("system_prompt") or "")[:240].strip()
    parts = [f"员工包 {name}（{pack_id}）"]
    if label:
        parts.append(label)
    if desc:
        parts.append(desc)
    elif prompt:
        parts.append(prompt)
    handlers = manifest_actions_handlers(manifest)
    if handlers:
        parts.append(f"handlers: {', '.join(handlers)}")
    return " — ".join(parts)[:800]


def _tool_parameters(manifest: dict[str, Any]) -> dict[str, Any]:
    props: dict[str, Any] = {
        "file_path": {
            "type": "string",
            "description": "待处理的文件路径（CSV/Excel/PDF/PPT/Word 等）",
        },
        "user_request": {
            "type": "string",
            "description": "用户对本次员工任务的补充说明",
        },
        "output_path": {"type": "string", "description": "可选：输出文件路径（生成类员工）"},
    }
    handlers = manifest_actions_handlers(manifest)
    pack_id = str(manifest.get("id") or "").lower()
    required: list[str] = []
    if "direct_python" in handlers and "generate" in pack_id:
        required = ["user_request"]
    elif "direct_python" in handlers:
        required = ["file_path"]
    return {"type": "object", "properties": props, "required": required}


@lru_cache(maxsize=1)
def _cached_tool_rows() -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for pack in list_installed_pack_records():
        pack_id = str(pack.get("pack_id") or "").strip()
        manifest = pack.get("manifest") if isinstance(pack.get("manifest"), dict) else {}
        if not pack_id or not manifest:
            continue
        pdir = resolve_pack_dir(pack_id)
        runtime_ok = pack_has_direct_python_runtime(pdir) if pdir else False
        handlers = manifest_actions_handlers(manifest)
        rows.append(
            {
                "pack_id": pack_id,
                "tool_name": pack_id,
                "legacy_tool_name": pack_id_to_legacy_tool_name(pack_id),
                "handlers": handlers,
                "runtime_ok": runtime_ok,
                "function": {
                    "name": pack_id,
                    "description": _tool_description(manifest, pack_id),
                    "parameters": _tool_parameters(manifest),
                },
            }
        )
    return tuple(rows)


def invalidate_employee_tool_cache() -> None:
    _cached_tool_rows.cache_clear()
    try:
        from app.mod_sdk.employee_planner_bridge import invalidate_employee_planner_registry

        invalidate_employee_planner_registry()
    except RECOVERABLE_ERRORS:
        pass
    logger.debug("employee tool registry cache cleared")


def build_employee_pack_tool_definitions() -> list[dict[str, Any]]:
    """OpenAI function 规格（tool name = pack_id）。"""
    return [
        {"type": "function", "function": dict(row["function"])}
        for row in _cached_tool_rows()
        if row.get("function")
    ]


def build_employee_pack_tools_detail() -> list[dict[str, Any]]:
    return [
        {
            "pack_id": row["pack_id"],
            "tool_name": row["tool_name"],
            "legacy_tool_name": row["legacy_tool_name"],
            "handlers": row.get("handlers") or [],
            "runtime_ok": bool(row.get("runtime_ok")),
            "installed": True,
        }
        for row in _cached_tool_rows()
    ]


def resolve_tool_to_pack_id(tool_name: str) -> str | None:
    name = str(tool_name or "").strip()
    if not name:
        return None
    for row in _cached_tool_rows():
        if name in (row.get("pack_id"), row.get("tool_name"), row.get("legacy_tool_name")):
            return str(row.get("pack_id") or "")
    if name.startswith(_LEGACY_PREFIX) and name.endswith(_LEGACY_SUFFIX):
        core = name[len(_LEGACY_PREFIX) : -len(_LEGACY_SUFFIX)]
        return core.replace("_", "-") if core else None
    return None


def is_employee_tool(name: str) -> bool:
    return resolve_tool_to_pack_id(name) is not None


def execute_employee_tool(
    name: str,
    args: dict[str, Any] | str,
    workspace_root: str | None = None,
    *,
    user_id: int = 0,
) -> str:
    from app.application.employee_runtime.executor import execute_employee_task_local

    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except json.JSONDecodeError:
            args = {}
    if not isinstance(args, dict):
        args = {}
    pack_id = resolve_tool_to_pack_id(name)
    if not pack_id:
        return json.dumps({"success": False, "error": "unknown employee tool"}, ensure_ascii=False)
    task = str(args.get("user_request") or args.get("task") or f"执行员工 {pack_id}")
    result = execute_employee_task_local(
        pack_id,
        task,
        args,
        user_id=user_id,
        workspace_root=workspace_root,
    )
    ok = bool(result.get("success", True) and not result.get("blocked_by_risk_gate"))
    return json.dumps(
        {
            "success": ok,
            "source": f"employee_pack:{pack_id}",
            "employee_id": pack_id,
            "output": result,
        },
        ensure_ascii=False,
    )


def build_employee_tools_status() -> dict[str, Any]:
    tools = build_employee_pack_tools_detail()
    tool_names = [t["tool_name"] for t in tools]
    try:
        from app.mod_sdk.employee_pack_compat import list_office_pack_catalog

        office_ids = set(list_office_pack_catalog().get("pack_ids") or [])
    except RECOVERABLE_ERRORS:
        office_ids = set()
    installed_ids = {t["pack_id"] for t in tools}
    office_installed = sorted(office_ids & installed_ids) if office_ids else []
    return {
        "installed_employee_pack_count": len(tools),
        "registered_tool_count": len(tool_names),
        "registered_tool_names": tool_names,
        "employee_pack_tools": tools,
        "office_catalog_count": len(office_ids),
        "office_installed_count": len(office_installed),
        "office_installed_ids": office_installed,
        "missing_office_pack_ids": sorted(office_ids - installed_ids) if office_ids else [],
        "office_ready": bool(office_ids) and not (office_ids - installed_ids),
        "runtime_missing_pack_ids": [t["pack_id"] for t in tools if not t.get("runtime_ok")],
    }


__all__ = [
    "build_employee_pack_tool_definitions",
    "build_employee_pack_tools_detail",
    "build_employee_tools_status",
    "execute_employee_tool",
    "invalidate_employee_tool_cache",
    "is_employee_tool",
    "pack_id_to_legacy_tool_name",
    "resolve_tool_to_pack_id",
]
