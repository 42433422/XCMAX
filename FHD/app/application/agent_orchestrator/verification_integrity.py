"""Retain host-frozen calls and successful receipts across ordinary run saves."""

from __future__ import annotations

import copy

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.run_models import AgentRun


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
        if successful and any(
            call.step_id == old.step_id and call.call_id not in prior_ids for call in run.tool_calls
        ):
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
        for key in ("verification_contract", "attempt_count"):
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
