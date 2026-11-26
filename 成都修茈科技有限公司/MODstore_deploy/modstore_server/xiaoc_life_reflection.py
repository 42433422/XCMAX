"""Review-only experience candidates from the existing strategic/life ledgers."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from modstore_server.strategic_portfolio import digest
from modstore_server.xiaoc_life_cognition import _closed_hypothesis, _number


def _sha(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        return None
    return result if result.utcoffset() is not None else None


def _cost(value: Any) -> int | None:
    number = _number(value, integer=True)
    return number if type(number) is int and number >= 0 else None


_FAILURE_ORIGINS = {
    "model": {
        "model_returned_no_usable_result",
        "model_usage_unknown",
        "platform_model_not_configured",
        "life_cycle_prompt_budget_exhausted",
        "platform_quota_unknown_or_exhausted",
    },
    "permission": {
        "life_policy_changed_or_lease_lost",
        "LifePolicyError",
        "portfolio_task_exceeds_life_cycle_budget",
    },
    "tool": {"research_returned_no_sources", "research_not_configured"},
    "environment": {"OperationalError", "ConnectionError", "TimeoutError", "OSError"},
}


def failure_classification(status: str, reason: Any) -> dict[str, str]:
    """Classify ONLY recognized runtime boundary codes, never infer root cause."""
    category = "not_applicable"
    if status in ("failed", "blocked", "interrupted", "unknown", "policy_changed"):
        category = (
            next(
                (kind for kind, codes in _FAILURE_ORIGINS.items() if reason in codes),
                "unknown",
            )
            if isinstance(reason, str)
            else "unknown"
        )
    return {
        "category": category,
        "basis": "runtime_boundary_code_not_verified_root_cause",
    }


def candidate_id(candidate: dict[str, Any]) -> str:
    # One original approved task, independent of later review timestamps.
    return "experience:" + digest(
        [
            candidate["owner_user_id"],
            candidate["decision_id"],
            candidate["proposal_sha256"],
            candidate["opportunity_id"],
        ]
    )


def candidate_refs(candidate: dict[str, Any]) -> list[str]:
    return [
        "portfolio:" + candidate["decision_id"],
        "proposal:" + candidate["proposal_sha256"],
        "task-result:" + candidate["result_sha256"],
        "hypothesis:" + candidate["snapshot_sha256"],
        "metric-evidence:" + candidate["metric_evidence_sha256"],
        "business-evidence:" + candidate["business_evidence_sha256"],
    ]


def _task_candidate(
    record: dict[str, Any], opportunity: dict[str, Any], review: dict[str, Any]
) -> dict[str, Any] | None:
    from modstore_server.strategic_execution_receipts import evaluate_execution_receipt
    from modstore_server.strategy_bets import CUSTOMER_ACCEPTANCE_METRIC, REVENUE_METRIC

    key = opportunity["opportunity_id"]
    task = record.get("tasks", {}).get(key, {})
    snapshot = record.get("hypothesis_outcomes", {}).get(key)
    if (
        task.get("status") not in ("completed", "failed")
        or not _sha(task.get("result_sha256"))
        or not isinstance(task.get("calls"), dict)
        or any(call.get("status") != "settled" for call in task["calls"].values())
        or not isinstance(snapshot, dict)
        or snapshot not in review.get("hypotheses", [])
        or snapshot.get("opportunity_id") != key
        or snapshot.get("hypothesis") != opportunity.get("hypothesis")
        or not _sha(snapshot.get("snapshot_sha256"))
        or digest({k: v for k, v in snapshot.items() if k != "snapshot_sha256"})
        != snapshot["snapshot_sha256"]
    ):
        return None
    execution = task.get("execution_receipt")
    if (
        not isinstance(execution, dict)
        or execution.get("truncated") is True
        or evaluate_execution_receipt(execution).status != task["status"]
    ):
        return None
    target, evidence = snapshot["hypothesis"], snapshot.get("evidence") or {}
    if not isinstance(target, dict) or not isinstance(evidence, dict):
        return None
    metric = _closed_hypothesis(
        {
            **snapshot,
            "metric_id": target.get("metric_id"),
            "threshold": target.get("threshold"),
            "direction": target.get("direction"),
            "value": evidence.get("value"),
        }
    )
    started, finished = _time(task.get("started_at")), _time(task.get("completed_at"))
    start, end = (_time(snapshot.get(k)) for k in ("window_start", "window_end"))
    reviewed, report_at = _time(snapshot.get("reviewed_at")), _time(review.get("at"))
    days = target.get("window_days")
    business_start = _time(review["business"].get("window_start"))
    business_end = _time(review["business"].get("window_end"))
    if (
        metric is None
        or started is None
        or finished is None
        or start is None
        or end is None
        or reviewed is None
        or report_at is None
        or type(days) is not int
        or not 1 <= days <= 365
        or started != start
        or end != start + timedelta(days=days)
        or not started <= finished <= end <= reviewed <= report_at
        or business_start is None
        or business_end is None
        or not business_start <= start <= end <= business_end
        or not _sha(evidence.get("evidence_sha256"))
        or not isinstance(evidence.get("source"), str)
        or not evidence["source"].strip()
    ):
        return None
    metric_id = metric["metric_id"]
    if metric_id == CUSTOMER_ACCEPTANCE_METRIC:
        if (
            evidence.get("basis")
            != "approved_goals_with_completed_artifact_and_customer_acceptance"
        ):
            return None
    elif metric_id == REVENUE_METRIC:
        if evidence.get("basis") != "attributed_verified_payments_in_approved_window":
            return None
    else:
        observed = _time(evidence.get("observed_at"))
        if observed is None or not start <= observed <= end:
            return None
    cost, estimate = _cost(task.get("accrued_cost_cents")), _cost(opportunity.get("cost_cents"))
    if cost is None or estimate is None or task.get("cost_basis") != "approved_tariff_accrual":
        return None
    failure = task["status"] == "failed" or metric["verdict"] == "miss"
    if not failure and (record.get("halted") or review.get("decision") == "stop"):
        return None
    return {
        "owner_user_id": record["owner_user_id"],
        "decision_id": record["decision_id"],
        "proposal_sha256": record["proposal_sha256"],
        "opportunity_id": key,
        "result_sha256": task["result_sha256"],
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "metric_evidence_sha256": evidence["evidence_sha256"],
        "business_evidence_sha256": review["business"]["order_refs_sha256"],
        "outcome": "failure" if failure else "success",
        "execution_status": task["status"],
        "metric_id": metric_id,
        "target": metric["threshold"],
        "actual": metric["value"],
        "deviation_from_target": metric["value"] - metric["threshold"],
        "direction": metric["direction"],
        "verdict": metric["verdict"],
        "approved_cost_estimate_cents": estimate,
        "accrued_cost_cents": cost,
        "cost_deviation_cents": cost - estimate,
        "window_start": snapshot["window_start"],
        "window_end": snapshot["window_end"],
        "finding_type": "observed_threshold_comparison_not_causal",
        "review_suggestion": (
            "review_execution_failure"
            if task["status"] == "failed"
            else "review_missed_target" if failure else "review_repeatability"
        ),
    }


def review_experiences(record: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """No independent evidence, no experience. Success is task-level only."""
    from modstore_server.strategic_customer_outcomes import KNOWN_DELIVERY_ATTRIBUTIONS

    summary: dict[str, Any] = {
        "outcome": "unknown",
        "finding_type": "unknown",
        "candidate_count": 0,
    }
    owner, decision, proposal = (
        record.get("owner_user_id"),
        record.get("decision_id"),
        record.get("proposal_sha256"),
    )
    authorization = record.get("authorization") or {}
    reviews = record.get("reviews") or []
    review = reviews[-1] if reviews else {}
    business = review.get("business") or {}
    selected = record.get("plan", {}).get("selected") or []
    start, end, reviewed = (
        _time(business.get("window_start")),
        _time(business.get("window_end")),
        _time(review.get("at")),
    )
    revenue, cost = _cost(business.get("revenue_cents")), _cost(review.get("accrued_cost_cents"))
    if (
        type(owner) is not int
        or owner <= 0
        or not isinstance(decision, str)
        or not decision
        or not _sha(proposal)
        or type(authorization.get("user_id")) is not int
        or authorization.get("user_id") != owner
        or authorization.get("proposal_sha256") != proposal
        or not authorization.get("actor")
        or review.get("usage_complete") is not True
        or review.get("observation_complete") is not True
        or business.get("status") != "verified"
        or business.get("attribution") not in KNOWN_DELIVERY_ATTRIBUTIONS
        or not _sha(business.get("order_refs_sha256"))
        or revenue is None
        or cost is None
        or review.get("cost_basis") != "approved_tariff_accrual_not_supplier_invoice"
        or start is None
        or end is None
        or reviewed is None
        or not start < end <= reviewed
        or not isinstance(selected, list)
        or not selected
        or any(not isinstance(key, str) or not key.strip() for key in selected)
        or len(set(selected)) != len(selected)
    ):
        return summary, []
    opportunities = record.get("opportunities", [])
    if not isinstance(opportunities, list) or any(
        not isinstance(item, dict) for item in opportunities
    ):
        return summary, []
    chosen = [item for item in opportunities if item.get("opportunity_id") in selected]
    if len({item["opportunity_id"] for item in chosen}) != len(chosen):
        return summary, []
    candidates = []
    for opportunity in chosen:
        candidate = _task_candidate(record, opportunity, review)
        if candidate is not None:
            candidates.append(candidate)
    candidate_ids = {c["opportunity_id"] for c in candidates}
    summary.update(
        finding_type="observed_business_measurement_not_causal",
        attributed_revenue_cents=revenue,
        accrued_cost_cents=cost,
        attributed_revenue_less_accrued_cost_cents=revenue - cost,
        candidate_count=len(candidates),
        selected_count=len(selected),
        outcome=(
            "failure"
            if any(c["outcome"] == "failure" for c in candidates)
            else "success" if candidate_ids == set(selected) else "no_conclusion"
        ),
    )
    return summary, candidates


def experience_candidate_facts(state: dict[str, Any]) -> list[dict[str, Any]]:
    """A review candidate is not an adopted memory or a capability score."""
    owner = state.get("owner_user_id")
    if type(owner) is not int or owner <= 0:
        return []
    for event in state.get("events", []):
        if event.get("kind") != "experience_candidate" or event.get("status") != "pending_review":
            continue
        details = event.get("details") or {}
        candidate = details.get("candidate")
        if (
            not isinstance(candidate, dict)
            or candidate.get("owner_user_id") != owner
            or candidate.get("outcome") not in ("success", "failure")
            or candidate.get("execution_status") not in ("completed", "failed")
            or (candidate["execution_status"] == "failed" and candidate["outcome"] != "failure")
            or not all(
                key in candidate
                for key in ("metric_id", "target", "actual", "review_suggestion", "finding_type")
            )
            or not all(
                _sha(candidate.get(key))
                for key in (
                    "proposal_sha256",
                    "result_sha256",
                    "snapshot_sha256",
                    "metric_evidence_sha256",
                    "business_evidence_sha256",
                )
            )
            or not all(
                isinstance(candidate.get(key), str) and candidate[key]
                for key in ("decision_id", "opportunity_id")
            )
            or event.get("id") != candidate_id(candidate)
            or details.get("candidate_sha256") != digest(candidate)
            or event.get("evidence_refs") != candidate_refs(candidate)
            or not any(
                goal.get("id") == details.get("goal_id")
                and goal.get("decision_id") == candidate["decision_id"]
                for goal in state.get("goals", [])
            )
        ):
            continue
        return [
            {
                "ref": event["id"],
                "text": "Verified task comparison awaiting experience review; not adopted memory.",
                "experience_candidate": {
                    key: candidate[key]
                    for key in (
                        "outcome",
                        "execution_status",
                        "metric_id",
                        "target",
                        "actual",
                        "review_suggestion",
                        "finding_type",
                    )
                },
            }
        ]
    return []
