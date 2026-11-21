"""工具启动和 ELT 单文件阶段预算。"""

from __future__ import annotations

from typing import Any

DEFAULT_TOOL_TIMEOUT_SECONDS = 60.0
_BATCH_ACTIONS = {("elt_import", "preview"), ("elt_import", "execute")}
ELT_LINKED_PREVIEW_TIMEOUT_SECONDS = 900.0
ELT_FILE_PHASES = {"preview": b"p", "linked_preview": b"l", "execute": b"e"}
# Reserve five seconds for the worker to return the stage receipt.
ELT_FILE_WATCHDOG_SECONDS = {b"p": 125.0, b"l": ELT_LINKED_PREVIEW_TIMEOUT_SECONDS + 5, b"e": 245.0}


def uses_elt_file_deadlines(tool_id: str, action: str, params: dict[str, Any]) -> bool:
    if (tool_id, action) not in _BATCH_ACTIONS:
        return False
    return bool(
        params.get("file_paths")
        or action == "preview"
        and params.get("file_path")
        or action == "execute"
        and (params.get("run_ids") or params.get("run_id"))
    )


def tool_timeout_seconds(
    tool_id: str, action: str, params: dict[str, Any] | None, default: float
) -> float:
    """ELT 批次启动后由隔离进程逐文件分配预算。"""
    base = default if default and default > 0 else DEFAULT_TOOL_TIMEOUT_SECONDS
    return max(base, 90.0) if (tool_id, action) in _BATCH_ACTIONS else base
