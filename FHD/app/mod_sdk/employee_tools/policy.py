"""Canonical workspace and approval policy adapter for employee writes."""

from __future__ import annotations

import os
from typing import Any, cast

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .ports import Payload


async def _check_write_gate(
    employee_id: str, tool_name: str, params: Payload, ctx: Payload
) -> Payload:
    """对代码修改工具检查 workspace_guard + write_approval gate。

    从 EmployeeRegistry 加载 manifest，构造 gate 并强制 scope_globs / forbidden_globs / 审批。
    gate 失败时返回 {ok: False, reason}；通过返回 {ok: True}。
    """
    try:
        from app.application.employee_runtime.workspace_guard import build_employee_gate
        from app.application.employee_runtime.write_approval import (
            build_write_approval_gate,
            compose_gates,
        )
        from app.infrastructure.mods.employee_registry import EmployeeRegistry
        from app.infrastructure.mods.mod_manager import get_mod_manager

        mgr = get_mod_manager()
        manifest: Payload | None = None
        roots: list[str] = []
        try:
            roots = list(mgr.all_mods_roots() or [])
        except RECOVERABLE_ERRORS:
            roots = []
        if not roots:
            primary = getattr(mgr, "mods_root", None)
            if primary:
                roots = [primary]
        for mods_root in roots:
            if not mods_root:
                continue
            registry = EmployeeRegistry(mods_root)
            for pack in registry.list_packs():
                if str(pack.get("id") or "") == employee_id:
                    manifest = pack
                    break
            if manifest:
                break
        if not manifest:
            return {"ok": False, "reason": f"未找到员工 {employee_id} 的 manifest，无法校验 scope"}
        config = manifest.get("employee_config_v2") or {}
        workspace_root = str(ctx.get("workspace_root") or os.getcwd())
        ws_gate = build_employee_gate(employee_id, manifest, config, workspace_root)
        write_gate = build_write_approval_gate(employee_id, params)
        gate = compose_gates(ws_gate, write_gate)
        if gate is None:
            return {"ok": True}
        return cast("dict[str, Any]", gate(tool_name, params))
    except RECOVERABLE_ERRORS as exc:
        return {"ok": False, "reason": f"gate 检查异常: {exc!r}"}
