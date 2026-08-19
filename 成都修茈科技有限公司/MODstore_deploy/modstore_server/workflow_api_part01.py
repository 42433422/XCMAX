# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.workflow_api")


def _guess_employee_id_from_empty_workflow(workflow: _facade().Workflow) -> str:
    """Best-effort extraction for old empty employee workflows.

    New employee workflows are fixed at creation time.  This fallback only helps
    already-created rows whose canvas is empty.  It is deliberately conservative
    and returns "" if no clear employee id is present.
    """
    text = f"{workflow.name or ''}\n{workflow.description or ''}"
    import re

    for pat in ("employee_id[=:：]\\s*([a-z0-9._-]+)", "pack_id[=:：]\\s*([a-z0-9._-]+)"):
        m = re.search(pat, text, flags=re.I)
        if m:
            return m.group(1).strip()
    m = re.search("\\b([a-z0-9][a-z0-9._-]{2,})\\b", text, flags=re.I)
    return m.group(1).strip() if m else ""


def _repair_empty_employee_workflow_graph(
    db: _facade().Session, workflow: _facade().Workflow
) -> bool:
    """Create start → employee → end for old empty employee workflow rows."""
    existing = (
        db.query(_facade().WorkflowNode)
        .filter(_facade().WorkflowNode.workflow_id == workflow.id)
        .count()
    )
    if existing:
        return False
    marker = f"{workflow.name or ''} {workflow.description or ''}"
    if "员工" not in marker and "employee" not in marker.lower():
        return False
    employee_id = _facade()._guess_employee_id_from_empty_workflow(workflow)
    if not employee_id:
        return False
    start = _facade().WorkflowNode(
        workflow_id=workflow.id,
        node_type="start",
        name="开始",
        config=_facade().json.dumps({}, ensure_ascii=False),
        position_x=80,
        position_y=140,
    )
    emp = _facade().WorkflowNode(
        workflow_id=workflow.id,
        node_type="employee",
        name=workflow.name or "执行员工",
        config=_facade().json.dumps(
            {
                "employee_id": employee_id,
                "task": (workflow.description or "根据工作流输入完成员工任务")[:400],
            },
            ensure_ascii=False,
        ),
        position_x=340,
        position_y=140,
    )
    end_node = _facade().WorkflowNode(
        workflow_id=workflow.id,
        node_type="end",
        name="结束",
        config=_facade().json.dumps({}, ensure_ascii=False),
        position_x=620,
        position_y=140,
    )
    db.add_all([start, emp, end_node])
    db.flush()
    db.add_all(
        [
            _facade().WorkflowEdge(
                workflow_id=workflow.id,
                source_node_id=start.id,
                target_node_id=emp.id,
                condition="",
            ),
            _facade().WorkflowEdge(
                workflow_id=workflow.id,
                source_node_id=emp.id,
                target_node_id=end_node.id,
                condition="",
            ),
        ]
    )
    db.commit()
    return True
