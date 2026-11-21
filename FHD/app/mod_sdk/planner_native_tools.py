"""里程碑 F：Planner 工具 handler 由 Mod backend 提供（优先于宿主 workflow）。"""

from __future__ import annotations

import inspect
import json
import logging
from functools import lru_cache
from typing import Any

from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

PLANNER_EXCEL_TOOLS_MOD_ID = "xcagi-planner-excel-tools"


def _truthy_env(name: str) -> bool:
    import os

    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def is_planner_native_tools_enabled() -> bool:
    if _truthy_env("XCAGI_DISABLE_PLANNER_NATIVE_TOOLS"):
        return False
    if _truthy_env("XCAGI_PLANNER_NATIVE_TOOLS"):
        return True
    return _discover_native_tool_mods() != []


def _discover_native_tool_mods() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        from app.infrastructure.mods.mod_manager import (
            get_mod_manager,
            is_mods_disabled,
        )

        if is_mods_disabled():
            return rows
        mgr = get_mod_manager()
        for meta in mgr.list_loaded_mods():
            tools = _native_tools_from_metadata(meta)
            if tools:
                rows.append(
                    {
                        "mod_id": meta.id,
                        "mod_path": meta.mod_path,
                        "tool_names": tools,
                    }
                )
    except RECOVERABLE_ERRORS:
        logger.debug("discover native planner mods via loaded failed", exc_info=True)

    if rows:
        return rows

    # 磁盘扫描（Mod 未热加载时）
    try:
        from app.infrastructure.mods.management.discovery import _mod_dir_candidates
        from app.infrastructure.mods.manifest import parse_manifest
        from app.shell.xcagi_mods_discover import mods_dir

        root = mods_dir()
        if not root:
            return rows

        for _entry, mod_path in _mod_dir_candidates(str(root)):
            parsed_meta = parse_manifest(mod_path)
            if parsed_meta is None:
                continue
            tools = _native_tools_from_metadata(parsed_meta)
            if tools:
                rows.append(
                    {
                        "mod_id": parsed_meta.id,
                        "mod_path": parsed_meta.mod_path,
                        "tool_names": tools,
                    }
                )
    except RECOVERABLE_ERRORS:
        logger.debug("discover native planner mods via disk failed", exc_info=True)
    return rows


def _native_tools_from_metadata(meta: Any) -> list[str]:
    try:
        manifest_path = __import__("pathlib").Path(meta.mod_path) / "manifest.json"
        if not manifest_path.is_file():
            return []
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        cfg = data.get("config") or {}
        raw = cfg.get("native_planner_tools") or cfg.get("planner_native_tools") or []
        if isinstance(raw, list):
            return [str(x).strip() for x in raw if str(x).strip()]
    except RECOVERABLE_ERRORS:
        pass
    return []


@lru_cache(maxsize=8)
def _load_handler_module(mod_path: str, mod_id: str):
    from app.infrastructure.mods.mod_manager import import_mod_backend_py

    return import_mod_backend_py(mod_path, mod_id, "tool_handlers")


def try_execute_native_planner_tool(
    name: str,
    args: dict[str, Any] | str,
    workspace_root: str | None = None,
    *,
    db_write_token: str | None = None,
    runtime_context: dict[str, Any] | None = None,
) -> tuple[str | None, str | None]:
    """若 Mod 已注册该工具则返回 (result_json, mod_id)，否则 (None, None)。"""
    if not is_planner_native_tools_enabled():
        return None, None

    tool = str(name or "").strip()
    if not tool:
        return None, None

    for row in _discover_native_tool_mods():
        raw_tool_names = row.get("tool_names")
        tool_names = raw_tool_names if isinstance(raw_tool_names, list) else []
        if tool not in tool_names:
            continue
        mod_id = str(row.get("mod_id") or "")
        mod_path = str(row.get("mod_path") or "")
        handler_started = False
        try:
            if not mod_path:
                raise ValueError("Registered native tool has no module path")
            mod = _load_handler_module(mod_path, mod_id)
            fn = getattr(mod, "run_native_tool", None)
            if not callable(fn):
                raise ValueError("Registered native tool has no executable handler")
            kwargs: dict[str, Any] = {
                "workspace_root": workspace_root,
                "db_write_token": db_write_token,
            }
            signature = inspect.signature(fn)
            if "runtime_context" in signature.parameters or any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            ):
                kwargs["runtime_context"] = runtime_context
            elif runtime_context:
                return (
                    json.dumps(
                        {
                            "success": False,
                            "error_code": "tool_context_unsupported",
                            "retryable": False,
                            "execution_status": "not_started",
                            "message": "模块工具尚不支持传递当前授权上下文",
                        },
                        ensure_ascii=False,
                    ),
                    mod_id,
                )
            # Inspect compatibility before execution. Retrying a TypeError from
            # inside a handler can repeat a write which already completed.
            signature.bind(tool, args, **kwargs)
            handler_started = True
            out = fn(tool, args, **kwargs)
            if out is None:
                raise ValueError("Registered native tool returned no execution receipt")
            return str(out), mod_id
        except BOUNDARY_ERRORS:
            # A plugin may raise a programming error after a side effect. This
            # isolation boundary must retain that unknown result, never call a
            # second handler or retry with fewer authorization arguments.
            logger.exception("native planner tool failed mod=%s tool=%s", mod_id, tool)
            return (
                json.dumps(
                    {
                        "success": False,
                        "error": "native_tool_failed",
                        "error_code": "native_tool_failed",
                        "mod_id": mod_id,
                        "outcome": "unknown" if handler_started else "not_started",
                        "execution_state": "unknown" if handler_started else "not_started",
                        "execution_status": ("unknown" if handler_started else "not_started"),
                        "retryable": False,
                        "reconciliation_required": handler_started,
                    },
                    ensure_ascii=False,
                ),
                mod_id,
            )
    return None, None


def list_native_planner_tools_summary() -> dict[str, Any]:
    mods = _discover_native_tool_mods()
    all_names: list[str] = []
    for m in mods:
        all_names.extend(m.get("tool_names") or [])
    return {
        "enabled": is_planner_native_tools_enabled(),
        "mod_count": len(mods),
        "mods": mods,
        "tool_names": sorted(set(all_names)),
    }


__all__ = [
    "PLANNER_EXCEL_TOOLS_MOD_ID",
    "is_planner_native_tools_enabled",
    "list_native_planner_tools_summary",
    "try_execute_native_planner_tool",
]
