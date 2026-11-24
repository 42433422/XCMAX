"""Read only the original Retort/GrowthBook frozen experiment measurement.

No traffic changes, experiment creation, model calls, or inferred causal claims.
"""

from __future__ import annotations

from typing import Any

from modstore_server.xiaoc_life_cognition import _number
from modstore_server.xiaoc_life_reflection import _sha, _time


def _bounded_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 128
        and all(c.isascii() and (c.isalnum() or c in "-_.:") for c in value)
    )


def frozen_experiment_projection(
    spec: dict[str, Any],
    progress: dict[str, Any],
    delivery: dict[str, Any],
    *,
    policy_digest: str,
) -> dict[str, Any]:
    """Historical effect estimates from the original fixed-window receipt only."""
    unknown = {"status": "unknown", "finding_type": "unknown"}
    if not progress:
        return unknown
    measured = progress.get("final_measurement")
    if not isinstance(measured, dict):
        return unknown
    decision = progress.get("decision")
    release = delivery.get("release_sha")
    lifecycle = spec.get("lifecycle") or {}
    deployed, started, ready, observed, closed = (
        _time(delivery.get("deployment_completed_at")),
        _time(progress.get("started_at")),
        _time(progress.get("evaluation_at")),
        _time(measured.get("observed_at")),
        _time(progress.get("closed_at")),
    )
    exposure_end = _time(progress.get("exposure_ends_at"))
    samples = measured.get("sample_size")
    minimum = spec.get("minimum_users")
    interval = measured.get("interval")
    effect = _number(measured.get("lift"))
    if (
        delivery.get("status") != "deployment_verified"
        or not isinstance(release, str)
        or len(release) != 40
        or any(c not in "0123456789abcdef" for c in release)
        or progress.get("release_sha") != release
        or not isinstance(delivery.get("identity"), dict)
        or delivery["identity"].get("git_sha") != release
        or not _sha(delivery["identity"].get("artifact_sha256"))
        or progress.get("identity") != delivery["identity"]
        or not _sha(policy_digest)
        or progress.get("policy_digest") != policy_digest
        or progress.get("rollout_verified") is not True
        or progress.get("execution_source_verified") is not True
        or not _sha(progress.get("final_snapshot_sha256"))
        or measured != progress.get("measurement")
        or measured.get("source") != "growthbook"
        or measured.get("status") not in ("running", "measured")
        or not _bounded_id(progress.get("experiment_id"))
        or measured.get("experiment_id") != progress["experiment_id"]
        or not _bounded_id(measured.get("snapshot_id"))
        or not _bounded_id(spec.get("metric"))
        or measured.get("metric_id") != spec["metric"]
        or measured.get("direction") != spec.get("direction", "increase")
        or type(samples) is not int
        or type(minimum) is not int
        or samples < minimum
        or minimum < 2
        or not isinstance(lifecycle.get("cohort_user_ids"), list)
        or samples > len(lifecycle["cohort_user_ids"])
        or decision not in ("promote", "rollback", "hold")
        or decision != measured.get("evaluated_decision")
        or progress.get("traffic") != ("candidate" if decision == "promote" else "control")
        or deployed is None
        or started is None
        or exposure_end is None
        or ready is None
        or observed is None
        or closed is None
        or not deployed <= started < exposure_end <= ready <= observed <= closed
        or effect is None
        or not isinstance(interval, list)
        or len(interval) != 2
    ):
        return unknown
    low, high = (_number(value) for value in interval)
    if low is None or high is None or not low <= effect <= high:
        return unknown
    # The original experiment engine already enforced randomization/guardrails.
    # Preserve the measured interval and decision, not a new causal attribution.
    return {
        "status": "inconclusive" if decision == "hold" else "measured",
        "finding_type": "historical_experiment_estimate_not_general_causal_proof",
        "experiment_id": measured["experiment_id"],
        "snapshot_id": measured["snapshot_id"],
        "snapshot_sha256": progress["final_snapshot_sha256"],
        "release_sha": release,
        "metric_id": measured["metric_id"],
        "sample_size": samples,
        "lift": effect,
        "interval": [low, high],
        "direction": measured["direction"],
        "decision": decision,
        "observation_start": started.isoformat(),
        "observation_end": exposure_end.isoformat(),
        "observed_at": observed.isoformat(),
    }


def original_experiment_projection(row: Any, delivery: dict[str, Any]) -> dict[str, Any]:
    """Use the existing approved policy verifier; never call advance_experiment."""
    from modstore_server.retort_feedback_experiments import _digest, approved_policy

    try:
        spec, effects = approved_policy(row)
    except (ValueError, KeyError, TypeError):
        return {"status": "unknown", "finding_type": "unknown"}
    progress = effects.get("experiment")
    if not isinstance(progress, dict):
        return {"status": "unknown", "finding_type": "unknown"}
    return frozen_experiment_projection(spec, progress, delivery, policy_digest=_digest(spec))


def bound_portfolio_experiment(
    session: Any,
    decision_id: str,
    proposal: dict[str, Any],
    state: dict[str, Any],
    item: dict[str, Any],
    *,
    now: Any,
) -> dict[str, Any] | None:
    """Read the original approved experiment tied to this exact strategic worker.

    Never create/advance an experiment, change exposure, or infer financial
    counterfactuals from a software or prompt experiment.
    """
    from modstore_server.business_decision_review import proposal_content
    from modstore_server.strategic_portfolio import PortfolioError, digest
    from modstore_server.strategic_workspace_bridge import KIND, original
    from modstore_server.strategic_workspace_receipts import validate_terminal

    remote = (item.get("input_data") or {}).get("remote_execution")
    if not isinstance(remote, dict) or remote.get("kind") != KIND:
        return None
    opportunity_id = item.get("opportunity_id")
    unknown = {
        "status": "unknown",
        "opportunity_id": opportunity_id,
        "finding_type": "unverified_original_experiment",
    }
    try:
        owner = proposal["owner_user_id"]
        proposal_sha = proposal["proposal_sha256"]
        authorization = state["authorization"]
        task = state["tasks"][opportunity_id]
        worker = task["worker_binding"]
        receipt = task["execution_receipt"]
        start, completed = _time(task["started_at"]), _time(task["completed_at"])
        if (
            type(owner) is not int
            or owner <= 0
            or not _sha(proposal_sha)
            or digest(proposal_content(proposal)) != proposal_sha
            or state.get("proposal_sha256") != proposal_sha
            or type(authorization.get("user_id")) is not int
            or authorization["user_id"] != owner
            or authorization.get("proposal_sha256") != proposal_sha
            or not authorization.get("actor")
            or not proposal["limits"].get("company_budget_id")
            or item not in proposal["opportunities"]
            or opportunity_id not in state["plan"]["selected"]
            or task.get("status") not in ("completed", "failed")
            or not _sha(task.get("result_sha256"))
            or not isinstance(task.get("calls"), dict)
            or any(
                not isinstance(call, dict) or call.get("status") != "settled"
                for call in task["calls"].values()
            )
            or not isinstance(worker, dict)
            or worker.get("decision_id") != decision_id
            or worker.get("opportunity_id") != opportunity_id
            or worker.get("owner_user_id") != owner
            or worker.get("proposal_sha256") != proposal_sha
            or worker.get("adapter") != KIND
            or worker.get("receipt_id") != remote["original_request_id"]
            or not worker.get("lease_token")
            or worker["lease_token"] != task.get("lease_token")
            or not isinstance(receipt, dict)
            or receipt.get("truncated")
            or digest(receipt) != task["result_sha256"]
            or (receipt.get("ok") is True) != (task["status"] == "completed")
            or start is None
            or completed is None
            or not start <= completed <= now
        ):
            return unknown
        request = {**remote, "binding": worker}
        row, _, effects = original(session, request, active=False)
        validate_terminal(session, request, receipt)
        delivery = receipt["remote_receipt"]["delivery"]
        result = original_experiment_projection(row, delivery)
        closed = _time((effects.get("experiment") or {}).get("closed_at"))
        observed = _time(result.get("observed_at"))
        began = _time(result.get("observation_start"))
        if (
            result.get("status") not in ("measured", "inconclusive")
            or not _sha(result.get("snapshot_sha256"))
            or began is None
            or observed is None
            or closed is None
            or not start <= began <= observed <= closed <= completed
        ):
            return unknown
        return {
            **result,
            "decision_id": decision_id,
            "opportunity_id": opportunity_id,
            "proposal_sha256": proposal_sha,
            "execution_result_sha256": task["result_sha256"],
            "original_request_id": remote["original_request_id"],
            "scope": "same_approved_retort_experiment_not_general_business_counterfactual",
        }
    except (PortfolioError, KeyError, TypeError, ValueError, AttributeError):
        return unknown
