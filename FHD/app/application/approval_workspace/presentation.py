"""Public approval views; execution receipts and record ordering share one projection."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.db.models.approval import ApprovalRequest

from .access import AI_WORKFLOW_NODE_NAME


def request_to_dict(
    req: ApprovalRequest,
    *,
    is_workflow: Callable[[ApprovalRequest], bool],
    include_records: bool = False,
) -> dict[str, Any]:
    """统一序列化（含 ``records`` 时间线，便于详情视图渲染）。"""
    base = req.to_dict()
    business_data = base.get("business_data")
    if isinstance(business_data, dict) and isinstance(
        business_data.get("workflow_execution"), dict
    ):
        base["workflow_execution"] = business_data["workflow_execution"]
    if is_workflow(req) and (not getattr(req, "current_node", None)):
        base["is_ai_workflow_approval"] = True
        base["current_node_name"] = base.get("current_node_name") or AI_WORKFLOW_NODE_NAME
        base["current_approvers"] = base.get("current_approvers") or []
    if include_records:
        records = (
            sorted(req.records or [], key=lambda r: r.action_time or datetime.min)
            if req.records
            else []
        )
        base["records"] = [r.to_dict() for r in records]
    return base
