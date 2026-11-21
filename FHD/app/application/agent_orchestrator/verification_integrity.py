"""Retain host-frozen calls and successful receipts across ordinary run saves."""

from __future__ import annotations

import copy

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.run_models import AgentRun


def unchanged_receipt_observation(previous, current) -> dict | None:
    """Retain only a bound negative observation; every execution fact stays frozen."""
    from app.application.agent_orchestrator.result_verification import PROTOCOL

    before, after = copy.deepcopy(previous.to_dict()), copy.deepcopy(current.to_dict())
    before["metadata"].pop("verification", None)
    report = after["metadata"].pop("verification", None)
    contract = previous.metadata.get("verification_contract") or {}
    if (
        before != after
        or not isinstance(contract, dict)
        or not isinstance(report, dict)
        or report.get("status") not in {"inconclusive", "failed"}
        or report.get("accepted") is not False
        or report.get("protocol") != contract.get("protocol")
        or contract.get("protocol") != PROTOCOL
    ):
        return None
    try:
        valid = (
            contract.get("contract_sha256")
            == canonical_hash(
                {key: value for key, value in contract.items() if key != "contract_sha256"}
            )
            and report.get("call_id") == contract.get("call_id") == previous.call_id
            and report.get("step_id") == previous.step_id
            and contract.get("step_id") == previous.step_id
            and contract.get("input_sha256") == canonical_hash(previous.params)
            and report.get("scope") == contract.get("scope")
            and report.get("contract_sha256") == contract.get("contract_sha256")
            and report.get("output_sha256")
            == previous.metadata.get("verification_output_sha256")
            == canonical_hash(previous.output)
            and report.get("evidence_sha256") == canonical_hash(report.get("checks"))
            and report.get("report_sha256")
            == canonical_hash(
                {key: value for key, value in report.items() if key != "report_sha256"}
            )
        )
    except (TypeError, ValueError):
        return None
    return copy.deepcopy(report) if valid else None


def preserve_verification_receipts(run: AgentRun, previous: AgentRun) -> None:
    from app.application.agent_orchestrator.result_verification import (
        PROTOCOL,
        pending_execution_receipt,
    )

    protected = [
        call
        for call in previous.tool_calls
        if isinstance(call.metadata.get("verification_contract"), dict)
        and call.metadata["verification_contract"].get("protocol") == PROTOCOL
    ]
    if not protected:
        return
    if (run.run_id, run.user_id, run.created_at) != (
        previous.run_id,
        previous.user_id,
        previous.created_at,
    ):
        raise ValueError("frozen verification run identity cannot change")
    incoming = {call.call_id: call for call in run.tool_calls}
    if len(incoming) != len(run.tool_calls):
        raise ValueError("duplicate verification call identity")
    prior_ids = {call.call_id for call in previous.tool_calls}
    missing = []
    for old in protected:
        successful = bool(old.metadata.get("verification_output_sha256")) and (
            old.output.get("success") is True or pending_execution_receipt(old.output)
        )
        added = [
            call
            for call in run.tool_calls
            if call.step_id == old.step_id and call.call_id not in prior_ids
        ]
        if successful and added and not _approved_preview_attempt(previous, run, added):
            raise ValueError("successful verification receipt cannot be replaced by another call")
        call = incoming.get(old.call_id)
        if call is None:
            missing.append(copy.deepcopy(old))
            continue
        if any(
            getattr(call, key) != getattr(old, key)
            for key in ("step_id", "node_id", "tool_id", "action")
        ) or canonical_hash(call.params) != canonical_hash(old.params):
            raise ValueError("frozen verification call identity or parameters cannot change")
        if (
            "continued_from_call_id" in call.metadata
            and "continued_from_call_id" not in old.metadata
        ):
            raise ValueError("frozen verification continuation identity cannot change")
        for key in ("verification_contract", "attempt_count", "continued_from_call_id"):
            if key not in old.metadata:
                continue
            if key in call.metadata and canonical_hash(call.metadata[key]) != canonical_hash(
                old.metadata[key]
            ):
                raise ValueError("frozen verification contract or attempt cannot change")
            call.metadata[key] = copy.deepcopy(old.metadata[key])
        if not successful:
            continue
        digest = old.metadata["verification_output_sha256"]
        if call.output and (canonical_hash(call.output) != digest or call.status != old.status):
            raise ValueError("successful verification receipt cannot change")
        if (
            "verification_output_sha256" in call.metadata
            and call.metadata["verification_output_sha256"] != digest
        ):
            raise ValueError("successful verification receipt digest cannot change")
        # A stale worker snapshot may omit the receipt; retain the already
        # committed fact without repeating its producing action.
        call.output = copy.deepcopy(old.output)
        call.status, call.error = old.status, old.error
        call.finished_at, call.duration_ms = old.finished_at, old.duration_ms
        call.metadata["verification_output_sha256"] = digest
    run.tool_calls = missing + run.tool_calls


def verified_pending_settlement(run: AgentRun, previous: AgentRun) -> bool:
    """A frozen accepted effect can settle only through bound independent evidence."""
    from app.application.agent_orchestrator.result_verification import (
        pending_execution_receipt,
        summarize_verification,
    )

    return bool(
        (previous.metadata.get("recovery") or {}).get("state") == "result_pending"
        and not run.metadata.get("non_retryable")
        and not run.metadata.get("recovery")
        and {call.call_id for call in run.tool_calls}
        == {call.call_id for call in previous.tool_calls}
        and {step.step_id for step in run.steps} == {step.step_id for step in previous.steps}
        and all(step.status in {"completed", "skipped"} for step in run.steps)
        and any(pending_execution_receipt(call.output) for call in run.tool_calls)
        and summarize_verification(run).get("accepted") is True
        and all(
            (call.metadata.get("verification") or {}).get("status") == "verified"
            for call in run.tool_calls
            if pending_execution_receipt(call.output)
        )
    )


def _approved_preview_attempt(previous: AgentRun, current: AgentRun, added: list) -> bool:
    """Append one approved preview attempt while retaining every original receipt."""
    from app.application.agent_orchestrator.result_verification import (
        PROTOCOL,
        _scope,
        latest_step_call,
    )
    from app.application.agent_orchestrator.run_lifecycle import approved_preview_continuation

    if len(added) != 1:
        return False
    call = added[0]
    step = next((s for s in previous.steps if s.step_id == call.step_id), None)
    prior = latest_step_call(previous, step) if step else None
    active_steps = [s for s in current.steps if s.step_id == call.step_id]
    contract = call.metadata.get("verification_contract")
    report = call.metadata.get("verification")
    if (
        step is None
        or prior is None
        or len(active_steps) != 1
        or not approved_preview_continuation(previous, step, prior)
        or current.status != "running"
        or current.metadata.get("approval_receipt") != previous.metadata.get("approval_receipt")
        or current.metadata.get("non_retryable")
        or current.metadata.get("stream_interruption")
        or (current.metadata.get("recovery") or {}).get("state") == "manual_reconciliation_required"
        or not isinstance(contract, dict)
        or not isinstance(report, dict)
    ):
        return False
    active = active_steps[0]
    attempt = step.attempt_count + 1
    try:
        return bool(
            call.metadata.get("continued_from_call_id") == prior.call_id
            and (call.node_id, call.tool_id, call.action, call.params)
            == (step.node_id, step.tool_id, step.action, step.params)
            == (active.node_id, active.tool_id, active.action, active.params)
            and call.metadata.get("attempt_count") == active.attempt_count == attempt
            and active.status == call.status == "running"
            and not call.output
            and not call.finished_at
            and not call.metadata.get("verification_output_sha256")
            and contract.get("protocol") == PROTOCOL
            and contract.get("contract_sha256")
            == canonical_hash(
                {key: value for key, value in contract.items() if key != "contract_sha256"}
            )
            and contract.get("scope")
            == _scope(current, current.metadata.get("runtime_context") or {})
            and (contract.get("step_id"), contract.get("node_id"), contract.get("call_id"))
            == (call.step_id, call.node_id, call.call_id)
            and (contract.get("tool_id"), contract.get("action")) == (call.tool_id, call.action)
            and contract.get("input_sha256") == canonical_hash(call.params)
            and contract.get("attempt") == attempt
            and report.get("protocol") == PROTOCOL
            and report.get("call_id") == call.call_id
            and report.get("status") == "pending"
            and report.get("accepted") is False
            and report.get("code") == "awaiting_execution_receipt"
            and report.get("checks") == []
        )
    except (TypeError, ValueError, OverflowError):
        return False
