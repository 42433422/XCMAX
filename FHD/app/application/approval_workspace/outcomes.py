"""Canonical execution receipts used by both configured and node-less approvals."""

from __future__ import annotations

import json
from typing import Any, TypedDict

from app.application.workflow.approval_persistence import canonical_workflow_outcome
from app.db.models.approval import ApprovalRequest, ApprovalStatus

from .protocols import JsonObject


class WorkflowOutcome(TypedDict):
    status: str
    success: bool
    code: str
    message: str
    workflow_executed: bool
    nodes_executed: int
    nodes_total: int


def safe_node_count(value: Any) -> int:
    try:
        return min(max(int(value), 0), 10000)
    except (TypeError, ValueError):
        return 0


def execution_outcome(execution: JsonObject | None) -> WorkflowOutcome:
    receipt = execution or {}
    executed = bool(receipt.get("workflow_executed"))
    success = executed and bool(receipt.get("success"))
    code, message = canonical_workflow_outcome(success=success, code=str(receipt.get("code") or ""))
    return {
        "status": ApprovalStatus.APPROVED.value if success else ApprovalStatus.CANCELLED.value,
        "success": success,
        "code": code,
        "message": message,
        "workflow_executed": executed,
        "nodes_executed": safe_node_count(receipt.get("nodes_executed")),
        "nodes_total": safe_node_count(receipt.get("nodes_total")),
    }


def persist_outcome(
    req: ApprovalRequest,
    *,
    status: str,
    success: bool,
    code: str,
    message: str,
    workflow_executed: bool,
    nodes_executed: int = 0,
    nodes_total: int = 0,
) -> None:
    """Join the caller's transaction and persist only the bounded receipt fields."""
    business_data = json.loads(req.business_data) if req.business_data else {}
    if not isinstance(business_data, dict):
        business_data = {}
    business_data["workflow_execution"] = {
        "status": status,
        "success": bool(success),
        "code": str(code or ""),
        "message": str(message or ""),
        "workflow_executed": bool(workflow_executed),
        "nodes_executed": safe_node_count(nodes_executed),
        "nodes_total": safe_node_count(nodes_total),
    }
    req.business_data = json.dumps(business_data, ensure_ascii=False, default=str)
