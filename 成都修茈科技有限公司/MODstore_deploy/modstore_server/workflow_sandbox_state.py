from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from modstore_server.models import Workflow, WorkflowEdge, WorkflowNode, WorkflowSandboxRun


def _safe_json_loads(raw: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}


def workflow_graph_fingerprint(db: Session, workflow_id: int) -> str:
    """Stable hash of executable workflow graph, excluding canvas-only layout."""
    nodes = (
        db.query(WorkflowNode)
        .filter(WorkflowNode.workflow_id == workflow_id)
        .order_by(WorkflowNode.id.asc())
        .all()
    )
    edges = (
        db.query(WorkflowEdge)
        .filter(WorkflowEdge.workflow_id == workflow_id)
        .order_by(WorkflowEdge.id.asc())
        .all()
    )
    payload = {
        "nodes": [
            {
                "id": int(n.id),
                "node_type": str(n.node_type or ""),
                "name": str(n.name or ""),
                "config": _safe_json_loads(n.config),
            }
            for n in nodes
        ],
        "edges": [
            {
                "id": int(e.id),
                "source_node_id": int(e.source_node_id),
                "target_node_id": int(e.target_node_id),
                "condition": str(e.condition or ""),
            }
            for e in edges
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def latest_sandbox_run(
    db: Session,
    workflow_id: int,
    *,
    user_id: Optional[int] = None,
    validate_only: Optional[bool] = False,
) -> Optional[WorkflowSandboxRun]:
    q = db.query(WorkflowSandboxRun).filter(WorkflowSandboxRun.workflow_id == workflow_id)
    if user_id is not None:
        q = q.filter(WorkflowSandboxRun.user_id == user_id)
    if validate_only is not None:
        q = q.filter(WorkflowSandboxRun.validate_only == validate_only)
    return q.order_by(WorkflowSandboxRun.created_at.desc(), WorkflowSandboxRun.id.desc()).first()


def sandbox_status_for_workflow(
    db: Session,
    workflow: Workflow,
    *,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    current_fp = workflow_graph_fingerprint(db, int(workflow.id))
    latest = latest_sandbox_run(db, int(workflow.id), user_id=user_id, validate_only=False)
    latest_fp = str(latest.graph_fingerprint or "") if latest else ""
    passed_for_current = bool(latest and latest.ok and latest_fp == current_fp)
    if not latest:
        status = "untested"
    elif latest_fp != current_fp:
        status = "stale"
    elif latest.ok:
        status = "pass"
    else:
        status = "fail"
    return {
        "workflow_id": int(workflow.id),
        "status": status,
        "graph_fingerprint": current_fp,
        "latest_run_id": int(latest.id) if latest else None,
        "latest_ok": bool(latest.ok) if latest else False,
        "latest_validate_only": bool(latest.validate_only) if latest else None,
        "latest_mock_employees": bool(latest.mock_employees) if latest else None,
        "latest_graph_fingerprint": latest_fp or None,
        "latest_at": latest.created_at.isoformat() if latest else None,
        "sandbox_passed_for_current_graph": passed_for_current,
    }


def record_workflow_sandbox_run(
    db: Session,
    *,
    workflow_id: int,
    user_id: int,
    report: Dict[str, Any],
    validate_only: bool,
    mock_employees: bool,
    graph_fingerprint: Optional[str] = None,
) -> WorkflowSandboxRun:
    fp = graph_fingerprint or workflow_graph_fingerprint(db, workflow_id)
    row = WorkflowSandboxRun(
        workflow_id=int(workflow_id),
        user_id=int(user_id),
        ok=bool((report or {}).get("ok")),
        validate_only=bool(validate_only),
        mock_employees=bool(mock_employees),
        graph_fingerprint=fp,
        report_json=json.dumps(report or {}, ensure_ascii=False),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def validate_workflow_sandbox_ready(
    db: Session,
    *,
    workflow_id: int,
    user_id: Optional[int] = None,
) -> list[str]:
    q = db.query(Workflow).filter(Workflow.id == int(workflow_id))
    if user_id is not None:
        q = q.filter(Workflow.user_id == int(user_id))
    workflow = q.first()
    if not workflow:
        return [f"workflow_id={workflow_id} 不存在或无权限"]
    status = sandbox_status_for_workflow(db, workflow, user_id=user_id)
    if status["sandbox_passed_for_current_graph"]:
        return []
    if status["status"] == "untested":
        return [f"workflow_id={workflow_id} 尚未通过沙箱测试"]
    if status["status"] == "stale":
        return [f"workflow_id={workflow_id} 已变更，请重新运行沙箱测试"]
    return [f"workflow_id={workflow_id} 最近一次沙箱测试未通过"]
