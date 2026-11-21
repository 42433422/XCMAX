"""Public approval views; execution receipts and record ordering share one projection."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.db.models.approval import ApprovalRequest
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .access import AI_WORKFLOW_NODE_NAME
from .outcomes import run_execution_receipt


def _current_run_receipt(
    req: ApprovalRequest, business_data: dict[str, Any]
) -> dict[str, Any] | None:
    """Refresh an approved request from its original run; never resume during a read."""
    if req.status != "approved" or not req.applicant_id:
        return None
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository
    from app.application.workflow.approval_persistence import _validated_snapshot
    from app.application.workflow.workflow_types import plan_fingerprint, plan_from_dict

    claim = business_data.get("agent_execution_claim")
    if not isinstance(claim, dict):
        return None
    unavailable = {
        "status": req.status,
        "success": False,
        "workflow_executed": False,
        "execution_state": "unknown",
        "code": "outcome_unknown",
        "requires_reconciliation": True,
        "retryable": False,
        "message": "暂时无法核实原执行回执，请核对原任务，勿重复提交。",
        "source": "agent_run_unavailable",
    }
    try:
        snapshot = _validated_snapshot(req)
        if (
            not snapshot
            or not snapshot["agent_run_id"]
            or (
                claim.get("agent_run_id") != snapshot["agent_run_id"]
                or claim.get("approved_step_id") != snapshot["approved_step_id"]
            )
        ):
            return unavailable
        run = get_agent_run_repository().get(snapshot["agent_run_id"])
        runtime = (run.metadata or {}).get("runtime_context") if run else None
        plan = plan_from_dict((run.metadata or {}).get("plan")) if run else None
        if (
            run is None
            or run.user_id != str(req.applicant_id)
            or not isinstance(runtime, dict)
            or str(runtime.get("tenant_id") or "") != str(req.tenant_id)
            or plan is None
            or run.plan_id != snapshot["plan"].plan_id
            or plan_fingerprint(plan) != plan_fingerprint(snapshot["plan"])
        ):
            return unavailable
        return {
            **run_execution_receipt(run),
            "status": req.status,
            "source": "agent_run",
        }
    except RECOVERABLE_ERRORS:
        return unavailable


def request_to_dict(
    req: ApprovalRequest,
    *,
    is_workflow: Callable[[ApprovalRequest], bool],
    include_records: bool = False,
) -> dict[str, Any]:
    """统一序列化（含 ``records`` 时间线，便于详情视图渲染）。"""
    base = req.to_dict()
    business_data = base.get("business_data")
    if isinstance(business_data, dict):
        if isinstance(business_data.get("workflow_execution"), dict):
            base["workflow_execution"] = business_data["workflow_execution"]
            current = _current_run_receipt(req, business_data)
            if current is not None:
                base["workflow_execution"] = current
        base["business_data"] = {
            key: value
            for key, value in business_data.items()
            if key
            not in {
                "durable_workflow_snapshot",
                "agent_execution_claim",
                "workflow_dispatch_claim",
            }
        }
        if isinstance(base.get("workflow_execution"), dict):
            base["business_data"]["workflow_execution"] = base["workflow_execution"]
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
