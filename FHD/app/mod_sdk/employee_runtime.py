"""employee_pack 安装后热加载：HTTP 路由 + Planner/workflow 工具注册表。"""

from __future__ import annotations

import logging
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def refresh_employee_pack_runtime(pack_id: str | None = None) -> dict[str, Any]:
    """安装/卸载员工包后刷新路由与工具 registry 缓存。"""
    from app.application.tools.workflow import invalidate_workflow_tool_registry
    from app.mod_sdk.employee_tool_registry import build_employee_tools_status

    invalidate_workflow_tool_registry()
    registered: list[str] = []
    try:
        from app.fastapi_app import get_fastapi_app
        from app.infrastructure.mods.mod_manager import (
            get_mod_manager,
            load_employee_pack_routes,
            register_employee_pack_routes,
        )

        app = get_fastapi_app()
        mm = get_mod_manager()
        pid = (pack_id or "").strip()
        if pid:
            if register_employee_pack_routes(app, mm, pid):
                registered.append(pid)
        else:
            load_employee_pack_routes(app, mm)
            registered = ["*"]
    except RECOVERABLE_ERRORS:
        logger.warning("refresh_employee_pack_runtime failed pack=%s", pack_id, exc_info=True)

    trigger_status: dict[str, Any] = {}
    try:
        from app.application.employee_runtime.triggers import refresh_employee_triggers

        trigger_status = refresh_employee_triggers(pack_id)
    except RECOVERABLE_ERRORS:
        logger.debug("refresh_employee_triggers skipped pack=%s", pack_id, exc_info=True)

    status = build_employee_tools_status()
    status["routes_reloaded"] = registered
    status["triggers"] = trigger_status
    tool_count = int(status.get("registered_tool_count") or 0)
    logger.info(
        "employee runtime refreshed pack=%s registered_tools=%s",
        pack_id or "*",
        tool_count,
    )
    return status


def warm_employee_tool_registry() -> dict[str, Any]:
    """启动时扫描 mods/_employees 并预热工具注册表。"""
    from app.application.tools.workflow import get_workflow_tool_registry
    from app.mod_sdk.employee_tool_registry import build_employee_tools_status

    reg = get_workflow_tool_registry()
    status = build_employee_tools_status()
    try:
        from app.application.employee_runtime.triggers import refresh_employee_triggers

        status["triggers"] = refresh_employee_triggers()
    except RECOVERABLE_ERRORS:
        logger.debug("warm employee triggers skipped", exc_info=True)
    logger.info(
        "employee tool registry warm scan: %s employee tools in workflow registry (total %s)",
        status.get("registered_tool_count"),
        len(reg),
    )
    return status


__all__ = ["refresh_employee_pack_runtime", "warm_employee_tool_registry"]
