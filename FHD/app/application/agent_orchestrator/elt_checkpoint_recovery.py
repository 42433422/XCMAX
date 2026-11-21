"""Recognize only the persisted, approved native ELT invocation on a queue lease."""

from __future__ import annotations

from uuid import UUID

from app.application.agent_orchestrator.approval_grant import _params_hash
from app.application.agent_orchestrator.run_lifecycle import requires_retry_reconciliation
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.workflow.workflow_types import plan_fingerprint, plan_from_dict
from app.domain.task_lifecycle.results import execution_result_outcome_unknown

ELT_CHECKPOINT_PROTOCOL = "elt-native-v1"


class EltCheckpointWorkerExited(Exception):
    """The isolated tool is reaped; reconcile its original file runs on the next claim."""


def checkpoint_step(run: AgentRun | None) -> AgentStep | None:
    if run is None or requires_retry_reconciliation(run):
        return None
    dispatch = run.metadata.get("dispatch")
    receipt = run.metadata.get("approval_receipt")
    if (
        not isinstance(dispatch, dict)
        or not isinstance(receipt, dict)
        or dispatch.get("elt_checkpoint_protocol") != ELT_CHECKPOINT_PROTOCOL
    ):
        return None
    step = next((s for s in run.steps if s.step_id == dispatch.get("approved_step_id")), None)
    if (
        step is None
        or (step.tool_id, step.action) != ("elt_import", "execute")
        or step.risk != "high"
        or step.status not in {"running", "pending"}
        or execution_result_outcome_unknown(step.output)
        or receipt.get("queue_approval") != "workspace_claim"
        or (receipt.get("step_id"), receipt.get("tool_id"), receipt.get("action"))
        != (step.step_id, step.tool_id, step.action)
        or not (receipt.get("approved_by") and receipt.get("approval_request_id"))
        or receipt.get("params_sha256") != _params_hash(step)
    ):
        return None
    plan = plan_from_dict(run.metadata.get("plan"))
    if (
        plan is None
        or plan.plan_id != run.plan_id
        or plan.metadata.get("durable_elt_batch") is not True
        or receipt.get("plan_sha256") != plan_fingerprint(plan)
    ):
        return None
    node = next((node for node in plan.nodes if node.node_id == step.node_id), None)
    if node is None or (node.tool_id, node.action, node.params, node.depends_on) != (
        step.tool_id,
        step.action,
        step.params,
        step.depends_on,
    ):
        return None
    paths = step.params.get("file_paths")
    try:
        if (
            not isinstance(paths, list)
            or not paths
            or any(not isinstance(path, str) or str(UUID(path)) != path for path in paths)
        ):
            return None
    except ValueError:
        return None
    return step
