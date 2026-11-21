"""Canonical execution receipts used by both configured and node-less approvals."""

from __future__ import annotations

import json
from typing import Any, TypedDict

from app.application.agent_orchestrator.trace_payloads import _payload_status
from app.application.workflow.approval_persistence import canonical_workflow_outcome
from app.db.models.approval import ApprovalRequest, ApprovalStatus
from app.domain.task_lifecycle.results import (
    execution_result_outcome_unknown,
    execution_result_pending_state,
)

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


def execution_handed_off(execution: JsonObject | None) -> bool:
    """The person approved and a worker owns the run. The import is not finished."""
    receipt = execution or {}
    return bool(receipt.get("execution_accepted")) and not bool(receipt.get("success"))


def run_outcome_unknown(run: Any) -> bool:
    """Keep uncertain nested tool receipts distinct from confirmed failures."""
    recovery = (getattr(run, "metadata", None) or {}).get("recovery") or {}
    return (
        isinstance(recovery, dict)
        and recovery.get("state") == "manual_reconciliation_required"
        or any(
            execution_result_outcome_unknown(output)
            for output in [
                {
                    "status": getattr(run, "status", ""),
                    "output": getattr(run, "final_output", None),
                },
                *[
                    step.output
                    for step in getattr(run, "steps", [])
                    if isinstance(getattr(step, "output", None), dict)
                ],
            ]
        )
    )


def run_execution_receipt(run: Any) -> JsonObject:
    """Read a bound AgentRun without dispatching, approving or mutating its state."""
    unknown = run_outcome_unknown(run)
    outputs = {
        "final_output": getattr(run, "final_output", None),
        "outputs": [
            step.output for step in run.steps if isinstance(getattr(step, "output", None), dict)
        ],
    }
    state = (
        "unknown"
        if unknown
        else execution_result_pending_state(outputs)
        or _payload_status({"agent_status": str(run.status or "unknown"), **outputs})
    )
    accepted = state in {
        "queued",
        "pending",
        "planning",
        "running",
        "retrying",
        "paused",
        "blocked",
        "waiting_user",
        "waiting_input",
        "waiting_auth",
        "waiting_approval",
    }
    success = state == "completed"
    code, message = canonical_workflow_outcome(success=success)
    if state == "unknown":
        code, message = (
            "outcome_unknown",
            "业务结果尚未确认；请核对原任务，勿重复提交。",
        )
    elif accepted:
        code = state
        message = {
            "paused": "审批已通过，原任务已暂停；请查询原任务状态。",
            "blocked": "审批已通过，原任务已阻断；请核对原任务状态。",
            "waiting_user": "审批已通过，原任务仍等待确认或补充信息。",
            "waiting_approval": "当前步骤已获批，后续步骤等待审批。",
        }.get(state, "审批已通过，原任务尚未完成，结果以任务回执为准。")
    return {
        "success": success,
        "execution_state": state,
        "execution_accepted": accepted,
        "workflow_executed": state in {"completed", "failed", "cancelled", "rejected"},
        "agent_run_id": run.run_id,
        "plan_id": str(run.plan_id or ""),
        "code": code,
        "message": message,
        "nodes_executed": len([step for step in run.steps if step.status == "completed"]),
        "nodes_total": len(run.steps),
        **({"requires_reconciliation": True, "retryable": False} if unknown else {}),
    }


def execution_outcome(execution: JsonObject | None) -> WorkflowOutcome:
    receipt = execution or {}
    executed = bool(receipt.get("workflow_executed"))
    success = executed and bool(receipt.get("success"))
    if receipt.get("code") == "outcome_unknown":
        return {
            "status": ApprovalStatus.APPROVED.value,
            "success": False,
            "code": "outcome_unknown",
            "message": "执行状态未确认，请核对业务数据，勿重复提交",
            "workflow_executed": False,
            "nodes_executed": 0,
            "nodes_total": 1,
        }
    if execution_handed_off(receipt):
        waiting_approval = bool(receipt.get("waiting_approval"))
        waiting_decision = bool(receipt.get("waiting_user_decision"))
        state = str(receipt.get("execution_state") or "queued")
        return {
            "status": ApprovalStatus.APPROVED.value,
            "success": False,
            "code": (
                "waiting_approval"
                if waiting_approval
                else "waiting_user_decision"
                if waiting_decision
                else state
            ),
            "message": (
                "当前步骤已获批，后续步骤等待审批"
                if waiting_approval
                else str(receipt.get("message") or "审批已通过，执行已交给调度器")
            ),
            "workflow_executed": False,
            "nodes_executed": safe_node_count(receipt.get("nodes_executed")),
            "nodes_total": safe_node_count(receipt.get("nodes_total")),
        }
    code, message = canonical_workflow_outcome(success=success, code=str(receipt.get("code") or ""))
    return {
        "status": (ApprovalStatus.APPROVED.value if success else ApprovalStatus.CANCELLED.value),
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
