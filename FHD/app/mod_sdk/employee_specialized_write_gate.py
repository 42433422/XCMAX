"""Write gate."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.mod_sdk.employee_specialized_runtime import _err, _ok, _run_cmd

_CODE_WRITE_TOOLS_LAZY: frozenset[str] | None = None


def _code_write_tools() -> frozenset[str]:
    global _CODE_WRITE_TOOLS_LAZY
    if _CODE_WRITE_TOOLS_LAZY is None:
        try:
            from app.application.employee_runtime.tool_scope import CODE_WRITE_TOOLS

            _CODE_WRITE_TOOLS_LAZY = CODE_WRITE_TOOLS
        except ImportError:
            _CODE_WRITE_TOOLS_LAZY = frozenset({"patch_file", "write_file"})
    return _CODE_WRITE_TOOLS_LAZY


async def tool_write_file(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """写入文件内容（受 scope_globs 约束，需 confirm=True 二次确认）。"""
    if not params.get("confirm"):
        return _err("write_file 需 params.confirm=True 二次确认")
    rel_path = str(params.get("path") or "").strip()
    content = str(params.get("content") or "")
    if not rel_path:
        return _err("缺少 params.path")
    workspace_root = str(ctx.get("workspace_root") or os.getcwd())
    root = Path(workspace_root).resolve()
    target = (root / rel_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return _err(f"路径 {rel_path} 越出 workspace_root")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as exc:  # noqa: BLE001  IO 边界：转为结构化错误
        return _err(f"写入失败: {exc!r}")
    return _ok(
        f"已写入 {rel_path}（{len(content)} 字符）",
        path=rel_path,
        bytes_written=len(content.encode()),
    )


async def tool_patch_file(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """应用 unified diff patch 到文件（受 scope_globs 约束，需 confirm=True）。"""
    if not params.get("confirm"):
        return _err("patch_file 需 params.confirm=True 二次确认")
    rel_path = str(params.get("path") or "").strip()
    patch = str(params.get("patch") or "")
    if not rel_path or not patch:
        return _err("缺少 params.path 或 params.patch")
    workspace_root = str(ctx.get("workspace_root") or os.getcwd())
    root = Path(workspace_root).resolve()
    target = (root / rel_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return _err(f"路径 {rel_path} 越出 workspace_root")
    if not target.is_file():
        return _err(f"目标文件不存在: {rel_path}")
    patch_tmp = root / f".tmp-patch-{os.getpid()}.diff"
    try:
        patch_tmp.write_text(patch, encoding="utf-8")
        check = await _run_cmd(["git", "apply", "--check", str(patch_tmp)], cwd=root, timeout=15)
        if not check.get("ok"):
            return _err(f"patch 校验失败: {check.get('stderr', '')[:500]}")
        apply = await _run_cmd(["git", "apply", str(patch_tmp)], cwd=root, timeout=15)
        if not apply.get("ok"):
            return _err(f"patch 应用失败: {apply.get('stderr', '')[:500]}")
    finally:
        try:
            patch_tmp.unlink(missing_ok=True)
        except OSError:
            pass
    return _ok(f"已应用 patch 到 {rel_path}", path=rel_path)


async def _check_write_gate(
    employee_id: str, tool_name: str, params: dict[str, Any], ctx: dict[str, Any]
) -> dict[str, Any]:
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
        manifest: dict[str, Any] | None = None
        roots: list[str] = []
        try:
            roots = list(mgr.all_mods_roots() or [])
        except Exception:  # noqa: BLE001  降级：用主 mods_root
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
        return gate(tool_name, params)
    except Exception as exc:  # noqa: BLE001  gate 边界：失败时阻断写操作
        return {"ok": False, "reason": f"gate 检查异常: {exc!r}"}
