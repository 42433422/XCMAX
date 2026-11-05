"""Execute or discard approved work without committing the approval transaction."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from app.application.workflow.approval_persistence import (
    AGENT_RUN_UNAVAILABLE_CODE,
    WORKFLOW_EXECUTION_FAILED_CODE,
    WORKFLOW_EXECUTION_SUCCESS_CODE,
    WORKFLOW_PLAN_UNAVAILABLE_CODE,
    WORKFLOW_SNAPSHOT_UNAVAILABLE_CODE,
    canonical_workflow_outcome,
    closed_loop_setup_failure_code,
)

from .protocols import JsonObject, PendingApprovals, WorkflowBackends

if TYPE_CHECKING:
    from app.application.workflow.workflow_types import PlanGraph


class WorkflowApprovalBridge:
    def __init__(
        self,
        backends: WorkflowBackends,
        errors: tuple[type[Exception], ...],
        logger: logging.Logger,
    ) -> None:
        self.backends = backends
        self.errors = errors
        self.logger = logger

    def has_pending(self, request_no: str | None) -> bool:
        request_id = str(request_no or "").strip()
        if not request_id:
            return False
        try:
            if self.backends.approvals().get_pending_workflow(request_id):
                return True
            return self.backends.pending_snapshot(request_id) is not None
        except self.errors:
            self.logger.warning("check pending AI workflow failed request_no=%s", request_id)
            return False

    @staticmethod
    def failure(request_id: str, code: str, **details: object) -> JsonObject:
        safe_code, message = canonical_workflow_outcome(success=False, code=code)
        return {
            "workflow_executed": False,
            "approval_request_id": request_id,
            "success": False,
            "code": safe_code,
            "message": message,
            **details,
        }

    def resume(self, *, request_no: str, opinion: str, approved_by: str = "") -> JsonObject | None:
        """Use the validated durable loader only when the in-memory work is absent."""
        request_id = str(request_no or "").strip()
        if not request_id:
            return None
        try:
            approvals = self.backends.approvals()
            approved = approvals.approve(request_id, opinion)
            workflow = approvals.get_pending_workflow(request_id)
            if not workflow:
                workflow = self.backends.execution_snapshot(request_id)
                if workflow is None:
                    return self.failure(
                        request_id, WORKFLOW_SNAPSHOT_UNAVAILABLE_CODE, approved_in_memory=approved
                    )
            if str(workflow.get("agent_run_id") or "").strip():
                return self._continue_agent(request_id, workflow, approved_by, approved, approvals)
            if not workflow.get("plan"):
                approvals.remove_pending_workflow(request_id)
                return self.failure(
                    request_id, WORKFLOW_PLAN_UNAVAILABLE_CODE, approved_in_memory=approved
                )
            return self._run_legacy(request_id, workflow, approved, approvals)
        except self.errors as exc:
            self.logger.warning(
                "resume pending AI workflow after approval failed request_no=%s type=%s",
                request_id,
                type(exc).__name__,
            )
            return self.failure(request_id, WORKFLOW_EXECUTION_FAILED_CODE)

    def _continue_agent(
        self,
        request_id: str,
        workflow: JsonObject,
        approved_by: str,
        approved: bool,
        approvals: PendingApprovals,
    ) -> JsonObject:
        run_id = str(workflow.get("agent_run_id") or "").strip()
        run = self.backends.agent().continue_run(
            run_id,
            approved_by=approved_by,
            approved_step_id=str(workflow.get("approved_step_id") or "").strip(),
            runtime_context=workflow.get("runtime_context", {}),
        )
        approvals.remove_pending_workflow(request_id)
        if run is None:
            return self.failure(request_id, AGENT_RUN_UNAVAILABLE_CODE, agent_run_id=run_id)
        success = run.status == "completed"
        code, message = canonical_workflow_outcome(
            success=success,
            code=WORKFLOW_EXECUTION_SUCCESS_CODE
            if success
            else (closed_loop_setup_failure_code(run) or WORKFLOW_EXECUTION_FAILED_CODE),
        )
        return {
            "workflow_executed": True,
            "approval_request_id": request_id,
            "agent_run_id": run.run_id,
            "approved_in_memory": approved,
            "success": success,
            "code": code,
            "plan_id": str(run.plan_id or ""),
            "intent": str(run.intent or ""),
            "message": message,
            "nodes_executed": len([step for step in run.steps if step.status == "completed"]),
            "nodes_total": len(run.steps),
            "tool_call_ids": [call.call_id for call in run.tool_calls],
        }

    def _run_legacy(
        self, request_id: str, workflow: JsonObject, approved: bool, approvals: PendingApprovals
    ) -> JsonObject:
        plan = cast("PlanGraph", workflow["plan"])
        context = workflow.get("runtime_context", {})
        engine = self.backends.engine()
        nodes = list(getattr(plan, "nodes", []) or [])
        restore_run = (
            self.backends.load_run(str(context.get("agent_run_id") or ""))
            if len(nodes) == 1
            and (getattr(nodes[0], "tool_id", None), getattr(nodes[0], "action", None))
            == ("system_maintenance", "restore_database")
            else None
        )
        result = engine.run(plan=plan, runtime_context=context, max_retries=1)
        run_id = self.backends.legacy_trace(
            request_id, context, result, run_before_restore=restore_run
        )
        approvals.remove_pending_workflow(request_id)
        success = bool(result.success)
        code, message = canonical_workflow_outcome(
            success=success,
            code=WORKFLOW_EXECUTION_SUCCESS_CODE if success else WORKFLOW_EXECUTION_FAILED_CODE,
        )
        return {
            "workflow_executed": True,
            "approval_request_id": request_id,
            "agent_run_id": run_id,
            "approved_in_memory": approved,
            "success": success,
            "code": code,
            "plan_id": getattr(plan, "plan_id", ""),
            "intent": getattr(plan, "intent", ""),
            "message": message,
            "nodes_executed": len(result.node_results or []),
            "nodes_total": len(nodes),
            "node_results": [
                {
                    "node_id": item.node_id,
                    "tool_id": item.tool_id,
                    "action": item.action,
                    "success": bool(item.success),
                    "error": "node_execution_failed" if item.error and not item.success else "",
                    "retries": int(getattr(item, "retries", 0) or 0),
                    "retryable": bool(getattr(item, "retryable", True)),
                    "recovery_hint": "retry_recommended"
                    if not item.success and bool(getattr(item, "retryable", True))
                    else "",
                }
                for item in (result.node_results or [])[:10]
            ],
        }

    def reject(self, *, request_no: str, reason: str) -> JsonObject | None:
        request_id = str(request_no or "").strip()
        if not request_id:
            return None
        try:
            approvals = self.backends.approvals()
            rejected = approvals.reject(request_id, reason)
            workflow = approvals.get_pending_workflow(request_id)
            workflow = workflow if isinstance(workflow, dict) else {}
            run_id = str(workflow.get("agent_run_id") or "").strip()
            if run_id:
                cancelled = self.backends.agent().cancel_run(
                    run_id, requested_by="approval_rejected"
                )
                cancelled_run_id = str(getattr(cancelled, "run_id", "") or "")
            else:
                cancelled_run_id = self.backends.legacy_trace(
                    request_id, workflow.get("runtime_context") or {}
                )
            removed = approvals.remove_pending_workflow(request_id)
            return {
                "workflow_executed": False,
                "approval_request_id": request_id,
                "agent_run_id": cancelled_run_id or run_id,
                "rejected_in_memory": rejected,
                "discarded_pending_workflow": removed is not None,
                "success": False,
                "code": "approval_rejected",
                "message": "审批已拒绝，AI 工作流已取消",
            }
        except self.errors as exc:
            self.logger.warning(
                "drop pending AI workflow after rejection failed request_no=%s type=%s",
                request_id,
                type(exc).__name__,
            )
            return {
                "workflow_executed": False,
                "approval_request_id": request_id,
                "success": False,
                "message": "审批已拒绝，但清理 AI 工作流失败",
            }
