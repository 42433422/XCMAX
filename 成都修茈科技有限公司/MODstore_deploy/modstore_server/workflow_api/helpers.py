from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from modstore_server.models import (
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    WorkflowTrigger,
)
from modstore_server.workflow_sandbox_state import (
    sandbox_status_for_workflow,
)


def _guess_employee_id_from_empty_workflow(workflow: Workflow) -> str:
    text = f"{workflow.name or ''}\n{workflow.description or ''}"
    for pat in (r"employee_id[=:：]\s*([a-z0-9._-]+)", r"pack_id[=:：]\s*([a-z0-9._-]+)"):
        m = re.search(pat, text, flags=re.I)
        if m:
            return m.group(1).strip()
    m = re.search(r"\b([a-z0-9][a-z0-9._-]{2,})\b", text, flags=re.I)
    return m.group(1).strip() if m else ""


def _repair_empty_employee_workflow_graph(db: Session, workflow: Workflow) -> bool:
    existing = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow.id).count()
    if existing:
        return False
    marker = f"{workflow.name or ''} {workflow.description or ''}"
    if "员工" not in marker and "employee" not in marker.lower():
        return False
    employee_id = _guess_employee_id_from_empty_workflow(workflow)
    if not employee_id:
        return False
    start = WorkflowNode(
        workflow_id=workflow.id,
        node_type="start",
        name="开始",
        config=json.dumps({}, ensure_ascii=False),
        position_x=80,
        position_y=140,
    )
    emp = WorkflowNode(
        workflow_id=workflow.id,
        node_type="employee",
        name=workflow.name or "执行员工",
        config=json.dumps(
            {
                "employee_id": employee_id,
                "task": (workflow.description or "根据工作流输入完成员工任务")[:400],
            },
            ensure_ascii=False,
        ),
        position_x=340,
        position_y=140,
    )
    end_node = WorkflowNode(
        workflow_id=workflow.id,
        node_type="end",
        name="结束",
        config=json.dumps({}, ensure_ascii=False),
        position_x=620,
        position_y=140,
    )
    db.add_all([start, emp, end_node])
    db.flush()
    db.add_all(
        [
            WorkflowEdge(
                workflow_id=workflow.id,
                source_node_id=start.id,
                target_node_id=emp.id,
                condition="",
            ),
            WorkflowEdge(
                workflow_id=workflow.id,
                source_node_id=emp.id,
                target_node_id=end_node.id,
                condition="",
            ),
        ]
    )
    db.commit()
    return True


def _serialize_workflow_snapshot(db: Session, workflow: Workflow) -> Dict[str, Any]:
    nodes = (
        db.query(WorkflowNode)
        .filter(WorkflowNode.workflow_id == workflow.id)
        .order_by(WorkflowNode.id.asc())
        .all()
    )
    edges = (
        db.query(WorkflowEdge)
        .filter(WorkflowEdge.workflow_id == workflow.id)
        .order_by(WorkflowEdge.id.asc())
        .all()
    )
    triggers = (
        db.query(WorkflowTrigger)
        .filter(WorkflowTrigger.workflow_id == workflow.id)
        .order_by(WorkflowTrigger.id.asc())
        .all()
    )
    return {
        "name": workflow.name,
        "description": workflow.description,
        "nodes": [
            {
                "local_id": n.id,
                "node_type": n.node_type,
                "name": n.name,
                "config": json.loads(n.config or "{}"),
                "position_x": n.position_x,
                "position_y": n.position_y,
            }
            for n in nodes
        ],
        "edges": [
            {
                "source_local_id": e.source_node_id,
                "target_local_id": e.target_node_id,
                "condition": e.condition or "",
            }
            for e in edges
        ],
        "triggers": [
            {
                "trigger_type": t.trigger_type,
                "trigger_key": t.trigger_key or "",
                "config": json.loads(t.config_json or "{}"),
                "is_active": bool(t.is_active),
            }
            for t in triggers
        ],
    }


def _restore_workflow_from_snapshot(
    db: Session, workflow: Workflow, snapshot: Dict[str, Any]
) -> None:
    db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == workflow.id).delete()
    db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow.id).delete()
    db.flush()

    local_to_new: Dict[int, int] = {}
    for raw in snapshot.get("nodes") or []:
        node = WorkflowNode(
            workflow_id=workflow.id,
            node_type=str(raw.get("node_type") or "").strip() or "start",
            name=str(raw.get("name") or "节点"),
            config=json.dumps(raw.get("config") or {}),
            position_x=float(raw.get("position_x") or 0.0),
            position_y=float(raw.get("position_y") or 0.0),
        )
        db.add(node)
        db.flush()
        local_to_new[int(raw.get("local_id") or 0)] = int(node.id)

    for raw in snapshot.get("edges") or []:
        src = local_to_new.get(int(raw.get("source_local_id") or 0))
        tgt = local_to_new.get(int(raw.get("target_local_id") or 0))
        if not src or not tgt:
            continue
        edge = WorkflowEdge(
            workflow_id=workflow.id,
            source_node_id=src,
            target_node_id=tgt,
            condition=str(raw.get("condition") or ""),
        )
        db.add(edge)

    name = snapshot.get("name")
    if isinstance(name, str) and name.strip():
        workflow.name = name
    desc = snapshot.get("description")
    if isinstance(desc, str):
        workflow.description = desc
    workflow.updated_at = datetime.now(timezone.utc)


def _parse_positive_int(v: Any) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def _workflow_summary(db: Session, workflow: Workflow, user_id: int) -> Dict[str, Any]:
    sandbox_status = sandbox_status_for_workflow(db, workflow, user_id=user_id)
    return {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "is_active": workflow.is_active,
        "created_at": workflow.created_at.isoformat(),
        "updated_at": workflow.updated_at.isoformat(),
        "graph_fingerprint": sandbox_status["graph_fingerprint"],
        "sandbox_status": sandbox_status,
        "sandbox_passed_for_current_graph": sandbox_status["sandbox_passed_for_current_graph"],
    }


def _employee_id_matches(candidate_id: str, target_employee_id: str) -> bool:
    c = str(candidate_id or "").strip()
    t = str(target_employee_id or "").strip()
    if not c or not t:
        return False
    if c == t:
        return True
    return c.endswith(f"-{t}") or c.endswith(f"_{t}") or t.endswith(f"-{c}") or t.endswith(f"_{c}")


def _employee_matches_manifest_entry(entry: Dict[str, Any], employee_id: str) -> bool:
    if not isinstance(entry, dict):
        return False
    eid = str(entry.get("id") or "").strip()
    if eid and _employee_id_matches(eid, employee_id):
        return True
    label = str(entry.get("label") or "").strip()
    panel_title = str(entry.get("panel_title") or "").strip()
    return _employee_id_matches(label, employee_id) or _employee_id_matches(
        panel_title, employee_id
    )
