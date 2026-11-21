"""Continue only a verified, approved ELT preview while retaining its old receipt."""

from __future__ import annotations

import copy

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall
from app.domain.task_lifecycle.results import execution_result_requires_reconciliation
from app.utils.operational_errors import RECOVERABLE_ERRORS


def preview_resume_matches(step: AgentStep, call: ToolCall) -> bool:
    """Match a proposed parameter migration; this grants no execution permission."""
    if (step.tool_id, step.action, call.tool_id, call.action) != (
        "elt_import",
        "preview",
        "elt_import",
        "preview",
    ):
        return False
    output = call.output
    if not isinstance(output, dict) or not isinstance(call.params, dict):
        return False
    resume = output.get("resume_params")
    if (
        output.get("success") is not True
        or output.get("preview") is not True
        or output.get("requires_user_decision") is not True
        or not isinstance(output.get("question"), str)
        or not output["question"].strip()
        or not isinstance(resume, dict)
        or not resume
        or set(resume) - {"valid_rows_only", "accept_suggested"}
        or any(value is not True for value in resume.values())
    ):
        return False
    try:
        current = canonical_hash(step.params)
        return current != canonical_hash(call.params) and current == canonical_hash(
            {**call.params, **resume}
        )
    except (TypeError, ValueError, OverflowError):
        return False


def original_preview_step(step: AgentStep, call: ToolCall) -> AgentStep:
    """Read the old report against its original inputs, without mutating the run."""
    original = copy.deepcopy(step)
    original.params = copy.deepcopy(call.params)
    original.output = copy.deepcopy(call.output)
    original.attempt_count = int(call.metadata.get("attempt_count") or step.attempt_count)
    return original


def _continuation_state_allows(run: AgentRun) -> bool:
    recovery = run.metadata.get("recovery") or {}
    return bool(
        run.status in {"queued", "running", "waiting_user"}
        and not run.metadata.get("non_retryable")
        and not run.metadata.get("stream_interruption")
        and isinstance(recovery, dict)
        and recovery.get("state") != "manual_reconciliation_required"
    )


def approved_preview_continuation(run: AgentRun, step: AgentStep, call: ToolCall) -> bool:
    """Require the original complete proof and a new approval over the merged inputs."""
    if (
        not preview_resume_matches(step, call)
        or call.status != "completed"
        or execution_result_requires_reconciliation(call.output)
        or not _continuation_state_allows(run)
    ):
        return False
    from app.application.agent_orchestrator.approval_grant import approval_scope_matches
    from app.application.agent_orchestrator.result_verification import (
        PROTOCOL,
        step_verification_blocked,
    )

    report = call.metadata.get("verification") or {}
    contract = call.metadata.get("verification_contract") or {}
    if not isinstance(report, dict) or not isinstance(contract, dict):
        return False
    checks = report.get("checks")
    if (
        report.get("protocol") != PROTOCOL
        or report.get("status") != "verified"
        or report.get("accepted") is not True
        or report.get("call_id") != call.call_id
        or report.get("step_id") != step.step_id
        or report.get("scope") != contract.get("scope")
        or not isinstance(checks, list)
        or len(checks) != 1
        or not isinstance(checks[0], dict)
        or checks[0].get("source") != "elt_preview_snapshot"
        or checks[0].get("status") != "passed"
        or not isinstance(checks[0].get("evidence"), dict)
        or checks[0]["evidence"].get("business_effect_verified") is not False
        or checks[0]["evidence"].get("verification_scope") != "preview_snapshot"
    ):
        return False
    try:
        historical = copy.copy(run)
        historical.tool_calls = [call]
        return not step_verification_blocked(
            historical, original_preview_step(step, call)
        ) and approval_scope_matches(run, step)
    except RECOVERABLE_ERRORS:
        return False


def fresh_preview_call(
    run: AgentRun, step: AgentStep, old: ToolCall, new: ToolCall, *, previous: AgentRun
) -> bool:
    """Check the one new, unexecuted call admitted after the latest saved preview."""
    from app.application.agent_orchestrator.result_verification import PROTOCOL, _scope

    # Check the saved state before the repository restores omitted holds into a
    # stale worker's snapshot. A later merge of those holds cannot undo dispatch.
    if not _continuation_state_allows(previous) or not approved_preview_continuation(
        run, step, old
    ):
        return False
    contract = new.metadata.get("verification_contract")
    report = new.metadata.get("verification") or {}
    if not isinstance(contract, dict) or not isinstance(report, dict):
        return False
    try:
        attempt = int(old.metadata.get("attempt_count") or 0) + 1
        return bool(
            new.metadata.get("continued_from_call_id") == old.call_id
            and (new.step_id, new.node_id, new.tool_id, new.action)
            == (step.step_id, step.node_id, step.tool_id, step.action)
            and canonical_hash(new.params) == canonical_hash(step.params)
            and new.metadata.get("attempt_count") == step.attempt_count == attempt
            and new.status == "running"
            and not new.output
            and not new.finished_at
            and not new.metadata.get("verification_output_sha256")
            and contract.get("protocol") == PROTOCOL
            and contract.get("contract_sha256")
            == canonical_hash(
                {key: value for key, value in contract.items() if key != "contract_sha256"}
            )
            and contract.get("scope") == _scope(run, run.metadata.get("runtime_context") or {})
            and (contract.get("step_id"), contract.get("node_id"), contract.get("call_id"))
            == (new.step_id, new.node_id, new.call_id)
            and (contract.get("tool_id"), contract.get("action")) == (new.tool_id, new.action)
            and contract.get("input_sha256") == canonical_hash(step.params)
            and contract.get("attempt") == attempt
            and report.get("protocol") == PROTOCOL
            and report.get("call_id") == new.call_id
            and report.get("status") == "pending"
            and report.get("accepted") is False
            and report.get("code") == "awaiting_execution_receipt"
            and report.get("checks") == []
        )
    except (TypeError, ValueError, OverflowError):
        return False
