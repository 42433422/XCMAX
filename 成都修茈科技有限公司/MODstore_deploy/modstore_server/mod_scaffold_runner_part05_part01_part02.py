# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.mod_scaffold_runner")


def patch_workflow_graph_employee_nodes(
    db: _facade().Session,
    user: _facade().User,
    *,
    mod_dir: _facade().Path,
    workflow_results: _facade().List[_facade().Dict[str, _facade().Any]],
) -> _facade().Dict[str, _facade().Any]:
    """
    对每条工作流，确保存在 employee 节点且 config.employee_id 与 expected_pack_id 对齐。

    策略：
    - 若图里已有 employee 节点：把 **首个** 节点的 employee_id 覆盖为 expected_pack_id；
      其余保持不动（用户可以在画布手工调整）。
    - 若没有 employee 节点：在 start -> end 路径间 **插入一个** 新 employee 节点，
      连接 start -> employee -> end（若有从 start 直达 end 的边则删除）。
    幂等：已经正确对齐则不写入任何变更。
    """
    from modman.manifest_util import read_manifest
    from modstore_server.models import WorkflowEdge

    data, err = read_manifest(mod_dir)
    if err or not data:
        return {"ok": False, "error": err or "manifest 无效", "patches": []}
    rows = data.get("workflow_employees")
    if not isinstance(rows, list) or not rows:
        return {"ok": True, "patches": [], "note": "无员工，无需修图"}
    patches: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for idx, entry in enumerate(rows):
        if not isinstance(entry, dict):
            continue
        wf_id = _facade()._parse_positive_int(entry.get("workflow_id") or entry.get("workflowId"))
        if not wf_id:
            patches.append({"workflow_index": idx, "skipped": "无 workflow_id"})
            continue
        wf = db.query(_facade().Workflow).filter(_facade().Workflow.id == wf_id).first()
        if not wf:
            patches.append(
                {
                    "workflow_index": idx,
                    "workflow_id": wf_id,
                    "skipped": "workflow 不存在",
                }
            )
            continue
        if not getattr(user, "is_admin", False) and int(wf.user_id) != int(user.id):
            patches.append(
                {
                    "workflow_index": idx,
                    "workflow_id": wf_id,
                    "skipped": "当前用户无权修改",
                }
            )
            continue
        expected_pack_id, perr, _pack_manifest = _facade()._resolve_workflow_entry_pack_id(
            mod_dir, data, entry, idx
        )
        if perr or not expected_pack_id:
            patches.append(
                {
                    "workflow_index": idx,
                    "workflow_id": wf_id,
                    "skipped": perr or "无法推导 expected_pack_id",
                }
            )
            continue
        emp_rows = _facade()._employee_node_ids_for_workflow_cfg(db, wf_id)
        if emp_rows:
            first = emp_rows[0]
            cfg = first["cfg"]
            current_eid = str(cfg.get("employee_id") or "").strip()
            if current_eid == expected_pack_id and any(
                (
                    str(x["cfg"].get("employee_id") or "").strip() == expected_pack_id
                    for x in emp_rows
                )
            ):
                patches.append(
                    {
                        "workflow_index": idx,
                        "workflow_id": wf_id,
                        "action": "noop",
                        "employee_id": expected_pack_id,
                    }
                )
                continue
            cfg["employee_id"] = expected_pack_id
            if not str(cfg.get("task") or "").strip():
                cfg["task"] = str(entry.get("panel_summary") or "根据工作流上下文完成员工任务")[
                    :400
                ]
            try:
                first["node"].config = _facade().json.dumps(cfg, ensure_ascii=False)
                db.commit()
                patches.append(
                    {
                        "workflow_index": idx,
                        "workflow_id": wf_id,
                        "action": "update",
                        "node_id": first["node"].id,
                        "employee_id": expected_pack_id,
                    }
                )
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                patches.append(
                    {
                        "workflow_index": idx,
                        "workflow_id": wf_id,
                        "error": f"update failed: {e}",
                    }
                )
            continue
        try:
            start = (
                db.query(_facade().WorkflowNode)
                .filter(
                    _facade().WorkflowNode.workflow_id == wf_id,
                    _facade().WorkflowNode.node_type == "start",
                )
                .first()
            )
            end = (
                db.query(_facade().WorkflowNode)
                .filter(
                    _facade().WorkflowNode.workflow_id == wf_id,
                    _facade().WorkflowNode.node_type == "end",
                )
                .first()
            )
            if not start or not end:
                _facade()._ensure_workflow_start_end_skeleton(db, wf_id)
                db.flush()
                start = (
                    db.query(_facade().WorkflowNode)
                    .filter(
                        _facade().WorkflowNode.workflow_id == wf_id,
                        _facade().WorkflowNode.node_type == "start",
                    )
                    .first()
                )
                end = (
                    db.query(_facade().WorkflowNode)
                    .filter(
                        _facade().WorkflowNode.workflow_id == wf_id,
                        _facade().WorkflowNode.node_type == "end",
                    )
                    .first()
                )
            if not start or not end:
                patches.append(
                    {
                        "workflow_index": idx,
                        "workflow_id": wf_id,
                        "skipped": "图缺 start/end，自动补全后仍无法插入员工节点",
                    }
                )
                continue
            emp_node = _facade().WorkflowNode(
                workflow_id=wf_id,
                node_type="employee",
                name=str(entry.get("label") or "员工")[:256],
                config=_facade().json.dumps(
                    {
                        "employee_id": expected_pack_id,
                        "task": str(entry.get("panel_summary") or "根据工作流上下文完成员工任务")[
                            :400
                        ],
                    },
                    ensure_ascii=False,
                ),
                position_x=float(getattr(start, "position_x", 0.0) or 0.0) + 220.0,
                position_y=float(getattr(start, "position_y", 0.0) or 0.0),
            )
            db.add(emp_node)
            db.flush()
            db.query(WorkflowEdge).filter(
                WorkflowEdge.workflow_id == wf_id,
                WorkflowEdge.source_node_id == start.id,
                WorkflowEdge.target_node_id == end.id,
            ).delete(synchronize_session=False)
            db.add(
                WorkflowEdge(
                    workflow_id=wf_id,
                    source_node_id=start.id,
                    target_node_id=emp_node.id,
                    condition="",
                )
            )
            db.add(
                WorkflowEdge(
                    workflow_id=wf_id,
                    source_node_id=emp_node.id,
                    target_node_id=end.id,
                    condition="",
                )
            )
            db.commit()
            patches.append(
                {
                    "workflow_index": idx,
                    "workflow_id": wf_id,
                    "action": "insert",
                    "node_id": emp_node.id,
                    "employee_id": expected_pack_id,
                }
            )
        except RECOVERABLE_ERRORS as e:
            db.rollback()
            patches.append(
                {
                    "workflow_index": idx,
                    "workflow_id": wf_id,
                    "error": f"insert failed: {e}",
                }
            )
    return {"ok": not any(("error" in p for p in patches)), "patches": patches}
