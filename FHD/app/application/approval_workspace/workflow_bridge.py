"""Execute or discard approved work without committing the approval transaction."""

from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING

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
    from app.application.agent_orchestrator.run_models import AgentRun


def _cross_module_run_id(workflow: JsonObject) -> str:
    direct = str(workflow.get("agent_run_id") or "").strip()
    if direct:
        return direct
    context = workflow.get("runtime_context")
    if not isinstance(context, dict):
        return ""
    checkpoint = context.get("cross_module_checkpoint")
    if isinstance(checkpoint, dict) and str(checkpoint.get("run_id") or "").strip():
        return str(checkpoint.get("run_id") or "").strip()
    return str(context.get("agent_run_id") or "").strip()


def _is_cross_module_workflow(workflow: JsonObject) -> bool:
    context = workflow.get("runtime_context")
    return isinstance(context, dict) and context.get("cross_module_http") is True


def _batch_absent(node: object, tenant_id: object) -> bool:
    from app.db.models import Product
    from app.db.models.purchase_unit import PurchaseUnit
    from app.db.session import get_db
    from app.infrastructure.tenant_scope import current_tenant_id

    try:
        tenant = int(str(tenant_id))
        ids = getattr(node, "params", {}).get("ids")
        if tenant <= 0 or tenant != current_tenant_id() or not isinstance(ids, list) or not ids:
            return False
        if any(type(item) is not int or item <= 0 for item in ids):
            return False
        model = Product if getattr(node, "tool_id", "") == "products" else PurchaseUnit
        with get_db() as db:
            return (
                not db.query(model.id).filter(model.tenant_id == tenant, model.id.in_(ids)).first()
            )
    except (ValueError, TypeError):
        return False


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
                        request_id,
                        WORKFLOW_SNAPSHOT_UNAVAILABLE_CODE,
                        approved_in_memory=approved,
                    )
            context = workflow.get("runtime_context") if isinstance(workflow, dict) else None
            if isinstance(context, dict) and context.get("cross_module_http") is True:
                # The sensitive write reads the durable snapshot. An in-memory copy is not enough.
                durable = self.backends.execution_snapshot(request_id)
                if not isinstance(durable, dict):
                    return self.failure(
                        request_id,
                        WORKFLOW_SNAPSHOT_UNAVAILABLE_CODE,
                        approved_in_memory=approved,
                    )
                from app.application.agent_orchestrator.cross_module_chain import (
                    resume_cross_module_http,
                )

                result = resume_cross_module_http(
                    durable, request_id=request_id, loaded_from_storage=True
                )
                approvals.remove_pending_workflow(request_id)
                return result
            if str(workflow.get("agent_run_id") or "").strip():
                return self._continue_agent(request_id, workflow, approved_by, approved, approvals)
            if isinstance(context, dict) and context.get("source") == "data_docking_auto_ingest":
                return self._release_docking(request_id, approvals)
            if isinstance(context, dict) and context.get("_approval_agent_run_required"):
                return self.failure(request_id, AGENT_RUN_UNAVAILABLE_CODE)
            if not workflow.get("plan"):
                approvals.remove_pending_workflow(request_id)
                return self.failure(
                    request_id,
                    WORKFLOW_PLAN_UNAVAILABLE_CODE,
                    approved_in_memory=approved,
                )
            # Legacy approval snapshots can no longer execute through the raw
            # WorkflowRuntime. Every resumable business plan must be bound to an
            # AgentRun before approval is submitted.
            return self.failure(request_id, AGENT_RUN_UNAVAILABLE_CODE)
        except self.errors as exc:
            self.logger.warning(
                "resume pending AI workflow after approval failed request_no=%s type=%s",
                request_id,
                type(exc).__name__,
            )
            return self.failure(request_id, WORKFLOW_EXECUTION_FAILED_CODE)

    def _release_docking(self, request_id: str, approvals: PendingApprovals) -> JsonObject:
        from app.application.elt.auto_ingest_service import get_auto_ingest_service
        from app.application.workflow.approval_persistence import claim_batch_dispatch
        from app.application.workflow.workflow_types import PlanGraph
        from app.infrastructure.tenant_scope import current_tenant_id

        durable = self.backends.execution_snapshot(request_id)
        plan = durable.get("plan") if isinstance(durable, dict) else None
        context = durable.get("runtime_context") if isinstance(durable, dict) else None
        if not isinstance(plan, PlanGraph) or len(plan.nodes) != 1 or not isinstance(context, dict):
            return self.failure(request_id, WORKFLOW_SNAPSHOT_UNAVAILABLE_CODE)
        node = plan.nodes[0]
        tenant = current_tenant_id()
        batch_id = str(node.params.get("batch_id") or "").strip()
        if (
            (node.tool_id, node.action) != ("data_docking", "auto_ingest")
            or node.node_id != "data_docking_write"
            or node.risk != "high"
            or node.idempotent
            or set(node.params) != {"batch_id"}
            or not batch_id
            or plan.plan_id != f"data-docking-{batch_id}"
            or (plan.metadata or {}).get("source") != "data_docking_auto_ingest"
            or context.get("source") != "data_docking_auto_ingest"
            or tenant is None
            or str(context.get("tenant_id")) != str(tenant)
            or not claim_batch_dispatch(request_id, plan, context)
        ):
            return self.failure(request_id, WORKFLOW_SNAPSHOT_UNAVAILABLE_CODE)
        try:
            result = get_auto_ingest_service().release_approved_batch(
                batch_id=batch_id, tenant_id=int(tenant)
            )
        except self.errors:
            return {**self.failure(request_id, "outcome_unknown"), "code": "outcome_unknown"}
        if not result.get("success"):
            return {**self.failure(request_id, "outcome_unknown"), "code": "outcome_unknown"}
        approvals.remove_pending_workflow(request_id)
        return {
            "success": False,
            "workflow_executed": False,
            "execution_accepted": True,
            "approval_request_id": request_id,
            "message": "审批已通过，入库任务已交付执行；结果以任务回执为准。",
        }

    def _continue_agent(
        self,
        request_id: str,
        workflow: JsonObject,
        approved_by: str,
        approved: bool,
        approvals: PendingApprovals,
    ) -> JsonObject:
        run_id = str(workflow.get("agent_run_id") or "").strip()
        # Resolve the validated durable snapshot through the injected backend on
        # every path, including in-memory pending workflows. This keeps tests and
        # production on the same tenant-scoped loader and avoids a second hidden
        # persistence route inside the bridge.
        durable = self.backends.execution_snapshot(request_id)
        if (
            not isinstance(durable, dict)
            or str(durable.get("agent_run_id") or "") != run_id
            or not str(durable.get("approved_step_id") or "")
        ):
            return self.failure(request_id, WORKFLOW_SNAPSHOT_UNAVAILABLE_CODE, agent_run_id=run_id)
        workflow_plan = workflow.get("plan")
        durable_plan = durable.get("plan")
        from app.application.workflow.workflow_types import (
            PlanGraph,
            plan_fingerprint,
            validate_plan_graph,
        )

        if (
            not isinstance(workflow_plan, PlanGraph)
            or not isinstance(durable_plan, PlanGraph)
            or validate_plan_graph(workflow_plan)
            or validate_plan_graph(durable_plan)
            or plan_fingerprint(workflow_plan) != plan_fingerprint(durable_plan)
        ):
            return self.failure(request_id, WORKFLOW_PLAN_UNAVAILABLE_CODE, agent_run_id=run_id)
        workflow = {
            **workflow,
            "plan": durable_plan,
            "runtime_context": durable.get("runtime_context") or {},
            "approved_step_id": durable.get("approved_step_id"),
        }
        context = workflow.get("runtime_context") or {}
        if context.get("_approval_agent_run_required") is not True:
            return self.failure(request_id, WORKFLOW_SNAPSHOT_UNAVAILABLE_CODE, agent_run_id=run_id)
        if context.get("_approval_agent_run_required"):
            current = self.backends.load_run(run_id)
            step_id = str(workflow.get("approved_step_id") or "").strip()
            waiting = next(
                (
                    step
                    for step in getattr(current, "steps", [])
                    if step.status == "waiting_user" and step_id in {step.node_id, step.step_id}
                ),
                None,
            )
            plan = workflow.get("plan")
            stored_plan = None
            if current is not None:
                from app.application.workflow.workflow_types import plan_from_dict

                stored_plan = plan_from_dict((current.metadata or {}).get("plan"))
            from app.application.workflow.planning_graph_policy import validate_required_params
            from app.application.workflow_registry_app import get_workflow_tool_registry

            if (
                current is None
                or current.plan_id != plan.plan_id
                or stored_plan is None
                or plan_fingerprint(stored_plan) != plan_fingerprint(plan)
                or validate_required_params(plan, get_workflow_tool_registry())
            ):
                return self.failure(request_id, WORKFLOW_PLAN_UNAVAILABLE_CODE, agent_run_id=run_id)
            steps = {item.node_id: item for item in current.steps}
            if set(steps) != {item.node_id for item in plan.nodes} or any(
                (node.tool_id, node.action, node.params, node.depends_on)
                != (
                    steps[node.node_id].tool_id,
                    steps[node.node_id].action,
                    steps[node.node_id].params,
                    steps[node.node_id].depends_on,
                )
                for node in plan.nodes
            ):
                return self.failure(request_id, WORKFLOW_PLAN_UNAVAILABLE_CODE, agent_run_id=run_id)
            from app.application.workflow.approval_persistence import _contract_digest

            if _contract_digest(plan) != _contract_digest(stored_plan):
                return self.failure(request_id, WORKFLOW_PLAN_UNAVAILABLE_CODE, agent_run_id=run_id)
            # The durable approval proof accepts either the public node id or
            # AgentStep id; resolve the validated tool contract through the
            # matched waiting step's canonical node id.
            node = next(
                (
                    node
                    for node in getattr(plan, "nodes", [])
                    if waiting is not None and node.node_id == waiting.node_id
                ),
                None,
            )
            if (
                current is None
                or current.status != "waiting_user"
                or waiting is None
                or node is None
                or (
                    node.tool_id != waiting.tool_id
                    or node.action != waiting.action
                    or node.params != waiting.params
                )
            ):
                return {
                    **self.failure(request_id, AGENT_RUN_UNAVAILABLE_CODE, agent_run_id=run_id),
                    "approval_claim_conflict": True,
                }
            from app.application.agent_orchestrator.tool_spec import validate_tool_call

            if not validate_tool_call(node.tool_id, node.action, node.params).ok:
                return self.failure(request_id, WORKFLOW_PLAN_UNAVAILABLE_CODE, agent_run_id=run_id)
            from app.application.workflow.approval_persistence import claim_agent_approval

            if not claim_agent_approval(
                request_id=request_id, agent_run_id=run_id, approved_step_id=step_id
            ):
                return {
                    **self.failure(request_id, AGENT_RUN_UNAVAILABLE_CODE, agent_run_id=run_id),
                    "approval_claim_conflict": True,
                }
        run = self.backends.agent().continue_run(
            run_id,
            approved_by=approved_by,
            approved_step_id=str(workflow.get("approved_step_id") or "").strip(),
            approval_request_id=request_id,
            runtime_context=workflow.get("runtime_context", {}),
        )
        approvals.remove_pending_workflow(request_id)
        if run is None:
            return self.failure(request_id, AGENT_RUN_UNAVAILABLE_CODE, agent_run_id=run_id)
        if run.status == "waiting_user":
            return self._request_next_approval(request_id, workflow, run, approvals, approved)
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

    def _request_next_approval(
        self,
        request_id: str,
        workflow: JsonObject,
        run: AgentRun,
        approvals: PendingApprovals,
        approved: bool,
    ) -> JsonObject:
        from app.application.workflow.workflow_types import (
            PlanGraph,
            plan_from_dict,
            validate_plan_graph,
        )

        plan = plan_from_dict((run.metadata or {}).get("plan"))
        waiting = next((step for step in run.steps if step.status == "waiting_user"), None)
        if (
            not isinstance(plan, PlanGraph)
            or waiting is None
            or plan.plan_id != run.plan_id
            or validate_plan_graph(plan)
        ):
            return self.failure(request_id, WORKFLOW_PLAN_UNAVAILABLE_CODE, agent_run_id=run.run_id)
        stored_steps = {item.node_id: item for item in run.steps}
        if set(stored_steps) != {item.node_id for item in plan.nodes} or any(
            (node.tool_id, node.action, node.params, node.depends_on)
            != (
                stored_steps[node.node_id].tool_id,
                stored_steps[node.node_id].action,
                stored_steps[node.node_id].params,
                stored_steps[node.node_id].depends_on,
            )
            for node in plan.nodes
        ):
            return self.failure(request_id, WORKFLOW_PLAN_UNAVAILABLE_CODE, agent_run_id=run.run_id)
        required = (plan.metadata or {}).get("approval_required_node_ids") or []
        if waiting.node_id not in required:
            return self.failure(request_id, WORKFLOW_EXECUTION_FAILED_CODE, agent_run_id=run.run_id)
        next_plan = copy.deepcopy(plan)
        node = next((item for item in next_plan.nodes if item.node_id == waiting.node_id), None)
        if node is None or node.tool_id != waiting.tool_id or node.action != waiting.action:
            return self.failure(request_id, WORKFLOW_PLAN_UNAVAILABLE_CODE, agent_run_id=run.run_id)
        node.params = copy.deepcopy(waiting.params)
        context = {**(workflow.get("runtime_context") or {}), "_approval_agent_run_required": True}
        request = approvals.create_approval_request(
            plan_id=next_plan.plan_id,
            node=node,
            runtime_context=context,
            plan=next_plan,
            require_persistence=True,
        )
        next_id = str(request.request_id or "").strip()
        if not next_id or not approvals.attach_pending_agent_run(
            next_id, agent_run_id=run.run_id, approved_step_id=waiting.node_id
        ):
            return self.failure(request_id, AGENT_RUN_UNAVAILABLE_CODE, agent_run_id=run.run_id)
        return {
            "workflow_executed": False,
            "success": False,
            "execution_accepted": True,
            "waiting_approval": True,
            "approval_request_id": request_id,
            "next_approval_request_id": next_id,
            "agent_run_id": run.run_id,
            "approved_in_memory": approved,
            "plan_id": run.plan_id,
            "intent": run.intent,
            "message": "当前步骤已获批，后续步骤等待审批。",
            "nodes_executed": sum(step.status == "completed" for step in run.steps),
            "nodes_total": len(run.steps),
        }

    @staticmethod
    def _cancel_docking_batch(workflow: JsonObject) -> None:
        plan = workflow.get("plan") if isinstance(workflow, dict) else None
        batch_id = ""
        for node in list(getattr(plan, "nodes", []) or []):
            if (getattr(node, "tool_id", ""), getattr(node, "action", "")) != (
                "data_docking",
                "auto_ingest",
            ):
                continue
            batch_id = str((getattr(node, "params", None) or {}).get("batch_id") or "").strip()
            break
        if not batch_id:
            return
        context = workflow.get("runtime_context") if isinstance(workflow, dict) else None
        raw_tenant = context.get("tenant_id") if isinstance(context, dict) else None
        try:
            tenant_id = int(raw_tenant or 0)
        except (TypeError, ValueError):
            return
        if tenant_id <= 0:
            return
        try:
            from app.application.elt.auto_ingest_service import get_auto_ingest_service
            from app.infrastructure.tenant_scope import tenant_scope
            from app.utils.operational_errors import RECOVERABLE_ERRORS

            with tenant_scope(tenant_id):
                get_auto_ingest_service().cancel_unreleased_batch(
                    batch_id=batch_id, tenant_id=tenant_id
                )
        except RECOVERABLE_ERRORS:
            return

    def reject(self, *, request_no: str, reason: str) -> JsonObject | None:
        request_id = str(request_no or "").strip()
        if not request_id:
            return None
        try:
            approvals = self.backends.approvals()
            rejected = approvals.reject(request_id, reason)
            workflow = approvals.get_pending_workflow(request_id)
            if not isinstance(workflow, dict):
                from app.application.workflow.approval_persistence import (
                    load_rejected_workflow_snapshot,
                )

                workflow = load_rejected_workflow_snapshot(request_id)
            workflow = workflow if isinstance(workflow, dict) else {}
            run_id = _cross_module_run_id(workflow)
            if run_id and _is_cross_module_workflow(workflow):
                from app.application.agent_orchestrator.cross_module_chain import (
                    reject_cross_module_task,
                )

                rejected_run = reject_cross_module_task(run_id, reason)
                cancelled_run_id = str(getattr(rejected_run, "run_id", "") or run_id)
            elif run_id:
                cancelled = self.backends.agent().cancel_run(
                    run_id, requested_by="approval_rejected"
                )
                cancelled_run_id = str(getattr(cancelled, "run_id", "") or "")
            else:
                cancelled_run_id = ""
            self._cancel_docking_batch(workflow)
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
