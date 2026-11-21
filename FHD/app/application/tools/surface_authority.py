"""Bind browser/screen effects to the existing authenticated, approved Agent step."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_CALL: ContextVar[tuple[str, str, dict, dict] | None] = ContextVar("surface_call", default=None)


@contextmanager
def surface_invocation_scope(tool_id: str, action: str, params: dict, context: dict):
    # Only AgentToolExecutor enters this scope after its permission/idempotency gates.
    token = _CALL.set((tool_id, action, dict(params), dict(context)))
    try:
        yield
    finally:
        _CALL.reset(token)


def require_surface_authority(
    tool_id: str, action: str, params: dict, context: dict, *, approval_required: bool
) -> tuple[Any, Any]:
    from app.application.agent_orchestrator.approval_grant import _params_hash
    from app.application.agent_orchestrator.business_write_guard import recheck_worker_claim
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository
    from app.application.agent_orchestrator.task_background import task_execution_context
    from app.application.agent_orchestrator.tool_permission import approval_execution_denial
    from app.application.tool_execution_deadline import check_invocation_deadline
    from app.application.workflow.workflow_types import plan_fingerprint, plan_from_dict
    from app.infrastructure.auth.agent_mod_scope import _bound_actor

    held = _CALL.get()
    if held is None or held != (tool_id, action, params, context):
        raise PermissionError("surface tools require the unified Agent executor")
    actor = _bound_actor(context)
    check_invocation_deadline()
    recheck_worker_claim()
    if context.get("cancel_requested") is True or approval_execution_denial(
        tool_id, action, context
    ):
        raise PermissionError("task is not authorized to execute")
    run = get_agent_run_repository().get(str(context.get("run_id") or ""))
    stored = run.metadata.get("runtime_context", {}) if run else {}
    if (
        run is None
        or run.status != "running"
        or not isinstance(stored, dict)
        or stored.get("_actor_authorization") != context.get("_actor_authorization")
        or str(stored.get("tenant_id") or "") != str(context.get("tenant_id") or "")
        or str(stored.get("user_id") or "") != str(actor.id)
        or str(run.user_id) != str(actor.id)
        or not str(context.get("idempotency_key") or "").strip()
    ):
        raise PermissionError("browser task identity is not bound to an active run")
    step = next((s for s in run.steps if s.step_id == context.get("step_id")), None)
    if (
        step is None
        or step.status != "running"
        or (step.tool_id, step.action, step.params) != (tool_id, action, params)
        or context.get("idempotency_key") != task_execution_context(run, step)["idempotency_key"]
    ):
        raise PermissionError("browser task does not match the stored step")
    plan = plan_from_dict(run.metadata.get("plan"))
    node = next((n for n in plan.nodes if n.node_id == step.node_id), None) if plan else None
    if (
        plan is None
        or node is None
        or (node.tool_id, node.action, node.params, node.depends_on)
        != (
            step.tool_id,
            step.action,
            step.params,
            step.depends_on,
        )
    ):
        raise PermissionError("browser task does not match the authorized plan")
    if approval_required:
        receipt = run.metadata.get("approval_receipt") or {}
        if (receipt.get("step_id"), receipt.get("tool_id"), receipt.get("action")) != (
            step.step_id,
            tool_id,
            action,
        ) or not receipt.get("approved_by"):
            raise PermissionError("browser effects require approval of this exact step")
        if receipt.get("grant_id"):
            from app.db import HostSessionLocal
            from app.db.models.agent_approval import AgentApprovalConsumption

            with HostSessionLocal() as db:
                consumed = db.get(AgentApprovalConsumption, receipt["grant_id"])
                if (
                    consumed is None
                    or (consumed.run_id, consumed.step_id) != (run.run_id, step.step_id)
                    or receipt.get("params_sha256") != _params_hash(step)
                ):
                    raise PermissionError("browser approval consumption does not match")
        else:
            from app.application.workflow.approval_persistence import (
                load_workflow_snapshot_for_execution,
            )
            from app.infrastructure.tenant_scope import tenant_scope

            request_id = str(receipt.get("approval_request_id") or "")
            tenant = str(context.get("tenant_id") or "")
            if not tenant.isdigit() or int(tenant) <= 0:
                raise PermissionError("workspace approval requires a valid tenant")
            # The existing loader revalidates the persisted tenant, request status,
            # claimed run, complete plan and current tool-contract fingerprint.
            with tenant_scope(int(tenant)):
                snapshot = load_workflow_snapshot_for_execution(request_id) if request_id else None
            snapshot_plan = plan_from_dict(snapshot.get("plan")) if snapshot else None
            if (
                not snapshot
                or snapshot.get("agent_run_id") != run.run_id
                or snapshot.get("approved_step_id") not in {step.step_id, step.node_id}
                or snapshot_plan is None
                or plan_fingerprint(snapshot_plan) != plan_fingerprint(plan)
                or receipt.get("plan_sha256") != plan_fingerprint(plan)
            ):
                raise PermissionError("browser approval proof is missing or no longer executable")
    return actor, run
