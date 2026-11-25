"""Retain host-frozen calls and successful receipts across ordinary run saves."""

from __future__ import annotations

import copy
import hmac

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.run_models import AgentRun


def _catalog_observation_proof(call, report) -> str | None:
    """Authenticate a terminal readback without reopening its source during save."""
    output = call.output
    if not (
        call.tool_id == "catalog_products_v1"
        and call.action in {"append_price", "correct_price"}
        and output.get("success") is False
        and output.get("fresh_save") is False
        and output.get("retryable") is False
        and report.get("status") == "verified"
        and report.get("accepted") is True
        and (output.get("outcome"), output.get("operation_outcome"), report.get("code"))
        in (
            ("historical_saved", "saved", "result_catalog_historical_verified"),
            ("rejected_no_effect", "rejected_no_effect", "result_catalog_rejected"),
        )
    ):
        return None
    from app.mod_sdk.catalog_product_store import proof

    return proof(
        {
            "purpose": "xcagi.catalog-terminal-observation.v1",
            "report": {
                key: value
                for key, value in report.items()
                if key not in {"catalog_observation_proof", "report_sha256"}
            },
        }
    )


def unchanged_receipt_observation(previous, current) -> dict | None:
    """Retain bound observations while every execution fact stays frozen."""
    from app.application.agent_orchestrator.result_verification import PROTOCOL

    before, after = copy.deepcopy(previous.to_dict()), copy.deepcopy(current.to_dict())
    before["metadata"].pop("verification", None)
    report = after["metadata"].pop("verification", None)
    contract = previous.metadata.get("verification_contract") or {}
    if (
        before != after
        or not isinstance(contract, dict)
        or not isinstance(report, dict)
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
        negative = report.get("status") in {"inconclusive", "failed"} and (
            report.get("accepted") is False
        )
        if valid and not negative:
            signature = report.get("catalog_observation_proof")
            expected = _catalog_observation_proof(previous, report)
            valid = bool(
                isinstance(signature, str)
                and signature.isascii()
                and expected is not None
                and hmac.compare_digest(signature, expected)
            )
    except (TypeError, ValueError):
        return None
    return copy.deepcopy(report) if valid else None


def preserve_verification_receipts(run: AgentRun, previous: AgentRun) -> None:
    from app.application.agent_orchestrator.result_verification import (
        PROTOCOL,
        _scope,
        pending_execution_receipt,
        preview_continuation_params,
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
            from app.application.agent_orchestrator.approval_grant import approval_scope_matches

            prior_step = next(
                (step for step in previous.steps if step.step_id == old.step_id), None
            )
            current_step = next((step for step in run.steps if step.step_id == old.step_id), None)
            proposed = (
                preview_continuation_params(previous, prior_step, old) if prior_step else None
            )
            same_step_calls = [call for call in run.tool_calls if call.step_id == old.step_id]
            position = next(
                (i for i, call in enumerate(same_step_calls) if call.call_id == old.call_id), -1
            )
            successor = (
                same_step_calls[position + 1] if 0 <= position < len(same_step_calls) - 1 else None
            )
            contract = successor.metadata.get("verification_contract") if successor else None
            report = successor.metadata.get("verification") if successor else None
            if not (
                proposed is not None
                and successor is not None
                and (successor.node_id, successor.tool_id, successor.action)
                == (old.node_id, old.tool_id, old.action)
                and successor.params == proposed
                and (
                    successor.call_id in prior_ids
                    or (
                        current_step is not None
                        and prior_step is not None
                        and previous.status in {"queued", "running", "waiting_user"}
                        and run.status == "running"
                        and all(
                            not snapshot.metadata.get("non_retryable")
                            and not snapshot.metadata.get("stream_interruption")
                            and (snapshot.metadata.get("recovery") or {}).get("state")
                            != "manual_reconciliation_required"
                            for snapshot in (previous, run)
                        )
                        and run.metadata.get("approval_receipt")
                        == previous.metadata.get("approval_receipt")
                        and approval_scope_matches(previous, prior_step)
                        and current_step.params == proposed
                        and canonical_hash(successor.params) == canonical_hash(proposed)
                        and approval_scope_matches(run, current_step)
                        and sum(call.call_id not in prior_ids for call in same_step_calls) == 1
                        and successor.metadata.get("continued_from_call_id") == old.call_id
                        and type(successor.metadata.get("attempt_count")) is int
                        and successor.metadata["attempt_count"]
                        == current_step.attempt_count
                        == prior_step.attempt_count + 1
                        and current_step.status == successor.status == "running"
                        and not successor.output
                        and not successor.finished_at
                        and not successor.metadata.get("verification_output_sha256")
                        and isinstance(contract, dict)
                        and contract.get("protocol") == PROTOCOL
                        and contract.get("contract_sha256")
                        == canonical_hash(
                            {
                                key: value
                                for key, value in contract.items()
                                if key != "contract_sha256"
                            }
                        )
                        and contract.get("scope")
                        == _scope(run, run.metadata.get("runtime_context") or {})
                        and (
                            contract.get("step_id"),
                            contract.get("node_id"),
                            contract.get("call_id"),
                        )
                        == (successor.step_id, successor.node_id, successor.call_id)
                        and (contract.get("tool_id"), contract.get("action"))
                        == (successor.tool_id, successor.action)
                        and contract.get("input_sha256") == canonical_hash(successor.params)
                        and contract.get("attempt") == current_step.attempt_count
                        and isinstance(report, dict)
                        and report.get("protocol") == PROTOCOL
                        and report.get("call_id") == successor.call_id
                        and report.get("status") == "pending"
                        and report.get("accepted") is False
                        and report.get("code") == "awaiting_execution_receipt"
                        and report.get("checks") == []
                        and preview_continuation_params(
                            run, current_step, incoming.get(old.call_id, old)
                        )
                        == proposed
                    )
                )
            ):
                raise ValueError(
                    "successful verification receipt cannot be replaced by another call"
                )
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
