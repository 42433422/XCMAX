from __future__ import annotations

import json
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from modman.manifest_util import read_manifest
from modman.repo_config import load_config, resolved_library
from modman.store import iter_mod_dirs
from modstore_server.api.deps import _get_current_user
from modstore_server.infrastructure.db import get_db
from modstore_server.models import (
    User,
    Workflow,
    WorkflowNode,
    get_user_mod_ids,
)
from modstore_server.workflow_api.helpers import (
    _employee_id_matches,
    _employee_matches_manifest_entry,
    _parse_positive_int,
    _workflow_summary,
)

router = APIRouter()


@router.get("/employee-eligible", summary="获取员工可绑定的工作流")
async def list_employee_eligible_workflows(
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    workflows = (
        db.query(Workflow)
        .filter(Workflow.user_id == user.id, Workflow.is_active == True)  # noqa: E712
        .order_by(Workflow.updated_at.desc(), Workflow.id.desc())
        .all()
    )
    rows = [_workflow_summary(db, w, user.id) for w in workflows]
    eligible = [r for r in rows if r.get("sandbox_passed_for_current_graph")]
    return {"workflows": eligible, "all_workflows": rows, "total": len(eligible)}


@router.get("/by-employee", summary="按员工查询关联工作流")
async def list_workflows_by_employee(
    employee_id: str = Query(..., min_length=1, max_length=256),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    eid = (employee_id or "").strip()
    if not eid:
        raise HTTPException(400, "employee_id 不能为空")

    workflows = db.query(Workflow).filter(Workflow.user_id == user.id).all()
    workflow_by_id = {int(w.id): w for w in workflows}
    result_by_id: Dict[int, Dict] = {}
    node_hit_ids: set[int] = set()
    manifest_hit_ids: set[int] = set()
    errors: List[str] = []

    emp_nodes = (
        db.query(WorkflowNode)
        .join(Workflow)
        .filter(
            Workflow.user_id == user.id,
            WorkflowNode.node_type == "employee",
        )
        .all()
    )
    for n in emp_nodes:
        try:
            cfg = json.loads(n.config or "{}")
        except json.JSONDecodeError:
            errors.append(f"workflow_node[{n.id}] config 不是合法 JSON")
            continue
        hit = _employee_id_matches(str((cfg or {}).get("employee_id") or "").strip(), eid)
        if not hit:
            continue
        wid = int(n.workflow_id)
        w = workflow_by_id.get(wid)
        if not w:
            continue
        node_hit_ids.add(wid)
        result_by_id[wid] = {"id": wid, "name": w.name or f"工作流 {wid}", "source": "node"}

    try:
        try:
            from modstore_server import app as app_module

            lib = app_module._lib()
        except Exception:
            cfg = load_config()
            lib = resolved_library(cfg)
        allow_mod_ids = None if user.is_admin else set(get_user_mod_ids(user.id))
        for d in iter_mod_dirs(lib):
            mid = d.name
            if allow_mod_ids is not None and mid not in allow_mod_ids:
                continue
            data, err = read_manifest(d)
            if err or not isinstance(data, dict):
                errors.append(f"mod[{mid}] manifest 读取失败: {err or 'invalid'}")
                continue
            wf_rows = data.get("workflow_employees")
            if not isinstance(wf_rows, list):
                continue
            for row in wf_rows:
                if not _employee_matches_manifest_entry(row, eid):
                    continue
                wid = _parse_positive_int(row.get("workflow_id") or row.get("workflowId"))
                if wid <= 0 or wid in node_hit_ids or wid in manifest_hit_ids:
                    continue
                w = workflow_by_id.get(wid)
                if not w:
                    continue
                manifest_hit_ids.add(wid)
                result_by_id[wid] = {
                    "id": wid,
                    "name": w.name or f"工作流 {wid}",
                    "source": "manifest",
                }
    except Exception as e:
        errors.append(f"manifest 扫描失败: {e}")

    rows = sorted(result_by_id.values(), key=lambda x: int(x.get("id") or 0))
    return {
        "workflows": rows,
        "node_hits": len(node_hit_ids),
        "manifest_hits": len(manifest_hit_ids),
        "errors": errors,
    }
