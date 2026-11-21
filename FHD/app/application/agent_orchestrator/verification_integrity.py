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
    from app.application.agent_orchestrator.result_verification import PROTOCOL

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
        successful = (
            bool(old.metadata.get("verification_output_sha256"))
            and old.output.get("success") is True
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
