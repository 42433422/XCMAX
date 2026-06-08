# -*- coding: utf-8 -*-
"""Mod 工作流员工闭环：登记 employee_pack + 画布对齐 + 可执行性检查（单入口）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modstore_server.models import User


async def run_workflow_employee_closure(
    db: Session,
    user: User,
    *,
    mod_dir: Path,
    register_missing: bool = True,
    patch_canvas: bool = True,
    industry: str = "通用",
    workflow_results: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    一键完成员工可用性闭环：
    1. 可选：为未登记的 workflow_employees 批量登记 Catalog employee_pack
    2. 可选：修复画布 employee 节点 employee_id 与 pack_id 对齐
    3. 返回闭环前后 readiness 报告
    """
    from modstore_server.mod_scaffold_runner import (
        analyze_mod_employee_readiness,
        patch_workflow_graph_employee_nodes,
        register_mod_employee_packs_async,
    )

    wf_results: List[Dict[str, Any]] = list(workflow_results or [])
    readiness_before = analyze_mod_employee_readiness(db, user, mod_dir)

    pack_register: Dict[str, Any] | None = None
    if register_missing:
        pack_register = await register_mod_employee_packs_async(
            db,
            user,
            mod_dir=mod_dir,
            workflow_results=wf_results,
            industry=industry,
        )

    graph_patch: Dict[str, Any] | None = None
    if patch_canvas:
        graph_patch = patch_workflow_graph_employee_nodes(
            db,
            user,
            mod_dir=mod_dir,
            workflow_results=wf_results,
        )

    readiness_after = analyze_mod_employee_readiness(db, user, mod_dir)
    ok = bool(readiness_after.get("ok"))

    return {
        "ok": ok,
        "readiness_before": readiness_before,
        "readiness_after": readiness_after,
        "pack_register": pack_register,
        "graph_patch": graph_patch,
        "steps": {
            "register_missing": bool(register_missing),
            "patch_canvas": bool(patch_canvas),
        },
    }
