"""Read-only decision comparison on the original strategic portfolio ledger.

A forecast is an empirical result of comparable, closed observations, not an
LLM score or a claim of incremental causality. No action is always an option.
Only the existing human-approved portfolio can execute.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import Any, cast

from sqlalchemy import select

from modstore_server.db.db_base import get_session_factory
from modstore_server.db.strategic import StrategicDecision
from modstore_server.strategic_portfolio import (
    RESOURCES,
    SCHEMA,
    Opportunity,
    PortfolioError,
    _date,
    digest,
    optimize_portfolio,
)
from modstore_server.strategy_bets import (
    CUSTOMER_ACCEPTANCE_METRIC,
    REVENUE_METRIC,
    BetHypothesis,
    judge,
)

MIN_SAMPLES = 40
HISTORY_LIMIT = 256


def proposal_content(proposal: dict[str, Any]) -> dict[str, Any]:
    keys = ("schema", "owner_user_id", "goal", "period", "limits", "opportunities")
    content = {key: proposal[key] for key in keys}
    if "decision_review" in proposal:
        content["decision_review"] = proposal["decision_review"]
    return content


def treatment_id(item: dict[str, Any]) -> str:
    """Exact executable treatment and metric, not a similarity match on model text."""
    return digest(
        {
            key: item.get(key)
            for key in (
                "title",
                "task",
                "employee_id",
                "execution_binding",
                "input_data",
                "hypothesis",
                "customer_goal_ids",
                "customer_goal_bindings",
                *RESOURCES,
            )
        }
    )


def _sha(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _measured_source(
    hypothesis: BetHypothesis, evidence: dict[str, Any], start: datetime, end: datetime
) -> bool:
    """Validate the original metric-reader receipt, not a new causal attribution."""
    value = evidence.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return False
    source = evidence.get("source")
    if not isinstance(source, str) or not source.strip():
        return False
    if hypothesis.metric_id == REVENUE_METRIC:
        return (
            source in ("python_payment_orders", "java_postgresql_internal_api")
            and evidence.get("basis") == "attributed_verified_payments_in_approved_window"
            and value >= 0
        )
    if hypothesis.metric_id == CUSTOMER_ACCEPTANCE_METRIC:
        accepted = evidence.get("accepted_goals")
        total = evidence.get("target_goals")
        return (
            source == "CustomerValueReceipt:verified_outcome_and_customer_acceptance"
            and evidence.get("basis")
            == "approved_goals_with_completed_artifact_and_customer_acceptance"
            and type(accepted) is int
            and type(total) is int
            and 0 <= accepted <= total
            and total > 0
            and value == accepted / total
        )
    try:
        return start <= _date(evidence["observed_at"]) <= end
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def closed_sample(
    item: dict[str, Any], state: dict[str, Any], as_of: datetime
) -> dict[str, Any] | None:
    key = item["opportunity_id"]
    target = item.get("hypothesis")
    tasks = state.get("tasks")
    outcomes = state.get("hypothesis_outcomes")
    if not isinstance(tasks, dict) or not isinstance(outcomes, dict):
        return None
    task = tasks.get(key)
    snapshot = outcomes.get(key)
    if not target or not isinstance(task, dict) or not isinstance(snapshot, dict):
        return None
    calls = task.get("calls")
    if (
        task.get("status") not in {"completed", "failed"}
        or task.get("cost_basis") != "approved_tariff_accrual"
        or not _sha(task.get("result_sha256"))
        or not isinstance(calls, dict)
        or not all(
            isinstance(call, dict)
            and call.get("status") == "settled"
            and call.get("cost_basis") == "approved_tariff_accrual"
            and type(call.get("accrued_cost_cents")) is int
            and call["accrued_cost_cents"] >= 0
            for call in calls.values()
        )
        or type(task.get("accrued_cost_cents")) is not int
        or task["accrued_cost_cents"] != sum(call["accrued_cost_cents"] for call in calls.values())
        or snapshot.get("opportunity_id") != key
        or snapshot.get("hypothesis") != target
    ):
        return None
    evidence = snapshot.get("evidence")
    if not isinstance(evidence, dict) or not _sha(evidence.get("evidence_sha256")):
        return None
    value = evidence.get("value")
    if type(value) not in (int, float):
        return None
    try:
        if digest({k: v for k, v in snapshot.items() if k != "snapshot_sha256"}) != snapshot.get(
            "snapshot_sha256"
        ):
            return None
        hypothesis = BetHypothesis.model_validate(target)
        start = _date(snapshot["window_start"])
        end = _date(snapshot["window_end"])
        reviewed = _date(snapshot["reviewed_at"])
        completed = _date(task["completed_at"])
        if (
            start != _date(task["started_at"])
            or end != start + timedelta(days=hypothesis.window_days)
            or not start < end <= reviewed <= as_of
            or not start <= completed <= reviewed
            or not _measured_source(hypothesis, evidence, start, end)
        ):
            return None
        verdict = judge(hypothesis.metric_id, value, hypothesis.threshold, hypothesis.direction)
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        return None
    if verdict not in {"hit", "miss"} or snapshot.get("verdict") != verdict:
        return None
    return {
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "evidence_sha256": evidence["evidence_sha256"],
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "value": value,
        "hit": int(verdict == "hit"),
        "accrued_cost_cents": task["accrued_cost_cents"],
        "cost_basis": task["cost_basis"],
        "result_sha256": task["result_sha256"],
    }


def history(session: Any, owner: int, as_of: datetime) -> dict[str, list[dict[str, Any]]]:
    """Bounded same-owner original approval and independent measurement history."""
    rows = session.scalars(
        select(StrategicDecision)
        .where(
            StrategicDecision.scope == "strategy_portfolio",
            StrategicDecision.scope_ref.like(f"user:{owner}:%"),
            StrategicDecision.proposed_at <= as_of,
        )
        .order_by(StrategicDecision.updated_at.desc(), StrategicDecision.id.desc())
        .limit(HISTORY_LIMIT)
    )
    samples: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        try:
            proposal = json.loads(row.decision_payload_json or "{}")
            state = json.loads(row.execution_result_json or "{}")
            if not isinstance(proposal, dict) or not isinstance(state, dict):
                continue
            canonical_hash = digest(proposal_content(proposal))
        except (KeyError, TypeError, ValueError):
            continue
        authorization = state.get("authorization", {})
        if not isinstance(authorization, dict):
            continue
        if (
            proposal.get("schema") != SCHEMA
            or type(proposal.get("owner_user_id")) is not int
            or proposal["owner_user_id"] != owner
            or type(authorization.get("user_id")) is not int
            or authorization.get("user_id") != owner
            or not authorization.get("actor")
            or row.decided_by not in {"user", "council-vote"}
            or authorization.get("proposal_sha256") != proposal.get("proposal_sha256")
            or canonical_hash != proposal.get("proposal_sha256")
        ):
            continue
        opportunities = proposal.get("opportunities")
        if not isinstance(opportunities, list):
            continue
        for item in opportunities:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("opportunity_id"), str)
                or not item.get("execution_binding")
            ):
                continue
            sample = closed_sample(item, state, as_of)
            if sample:
                samples.setdefault(treatment_id(item), []).append(
                    {**sample, "decision_id": row.decision_id}
                )
    return samples


def forecast(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Train a constant empirical rate on earlier observations; test on later ones."""
    unique: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    seen_decisions: set[str] = set()
    last_end = ""
    for row in sorted(rows, key=lambda item: (item["window_end"], item["snapshot_sha256"])):
        if (
            row["evidence_sha256"] in seen_sources
            or row["decision_id"] in seen_decisions
            or row["window_start"] < last_end
        ):
            continue
        unique.append(row)
        last_end = row["window_end"]
        seen_sources.add(row["evidence_sha256"])
        seen_decisions.add(row["decision_id"])
    result: dict[str, Any] = {
        "status": "unknown_insufficient_independent_history",
        "sample_count": len(unique),
        "probability_of_target": None,
        "expected_metric_value": None,
        "expected_accrued_cost_cents": None,
        "risk_of_target_miss": None,
        "sample_refs": [row["snapshot_sha256"] for row in unique],
    }
    if len(unique) < MIN_SAMPLES:
        return result
    split = len(unique) // 2
    train, holdout = unique[:split], unique[split:]
    if len({row["hit"] for row in train}) < 2 or len({row["hit"] for row in holdout}) < 2:
        return {**result, "status": "unknown_insufficient_outcome_variation"}
    try:
        from scipy.stats import binomtest  # type: ignore[import-untyped]
        from sklearn.metrics import brier_score_loss  # type: ignore[import-untyped]
    except ImportError:
        return {**result, "status": "unknown_statistics_dependency_unavailable"}
    p = mean(row["hit"] for row in train)
    labels = [row["hit"] for row in holdout]
    interval = binomtest(sum(labels), len(labels)).proportion_ci(confidence_level=0.95)
    diagnostics = {
        "train_count": len(train),
        "holdout_count": len(holdout),
        "training_rate": p,
        "holdout_rate": mean(labels),
        "holdout_rate_interval_95": [float(interval.low), float(interval.high)],
        "holdout_brier": float(brier_score_loss(labels, [p] * len(labels))),
    }
    if not interval.low <= p <= interval.high:
        return {**result, **diagnostics, "status": "unknown_rate_failed_temporal_check"}
    return {
        **result,
        **diagnostics,
        "status": "historical_constant_rate_temporally_checked",
        "probability_of_target": p,
        "risk_of_target_miss": 1 - p,
        "expected_metric_value": mean(row["value"] for row in train),
        "expected_accrued_cost_cents": mean(row["accrued_cost_cents"] for row in train),
        "basis": "same_frozen_treatment_observations_not_causal_return_or_general_risk",
    }


def compare_options(
    *,
    owner: int,
    primary: dict[str, Any],
    limits: dict[str, Any],
    alternatives: list[dict[str, Any]],
    context_sha256: str,
    evidence_refs: list[str],
    request_sha256: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Use the original solver per exclusive choice; only one can enter approval."""
    from modstore_server.strategic_company_resources import remaining
    from modstore_server.strategic_execution_contract import freeze_execution

    now = datetime.now(UTC)
    with get_session_factory()() as session:
        capacity = remaining(session, {"owner_user_id": owner, "limits": limits})
        historical = history(session, owner, now)
    effective = dict(limits)
    if capacity is not None:
        for key in RESOURCES:
            effective[key] = min(effective[key], capacity[key])
        effective["max_parallel"] = min(effective["max_parallel"], capacity["slots"])
    effective["cost_cents"] = min(effective["cost_cents"], effective["stop_loss_cents"])
    effective["stop_loss_cents"] = min(effective["stop_loss_cents"], effective["cost_cents"])
    options: list[dict[str, Any]] = [
        {
            "option_id": "no_action",
            "title": "不采取行动",
            "feasible": True,
            "reservation_cap": dict.fromkeys(RESOURCES, 0),
            "forecast": {
                "status": "unknown_counterfactual_not_observed",
                "expected_metric_value": None,
                "probability_of_target": None,
                "risk_of_target_miss": None,
                "direct_new_action_cost_cents": 0,
            },
        }
    ]
    candidates = [primary]
    rejected = []
    normalized_tasks = {" ".join(primary["task"].split()).casefold()}
    for alt in alternatives[:2]:
        task = alt.get("task")
        normalized = " ".join(task.split()).casefold() if isinstance(task, str) else ""
        if not normalized or normalized in normalized_tasks:
            rejected.append(
                {
                    "option_id": "review-" + digest(alt)[:20],
                    "title": alt["title"],
                    "evidence_refs": alt["evidence_refs"],
                    "feasible": False,
                    "reason": "missing_distinct_executable_task",
                    "forecast": {"status": "unknown_not_executable"},
                }
            )
            continue
        requested_caps = alt.get("resource_caps")
        if requested_caps is not None and (
            not isinstance(requested_caps, dict)
            or set(requested_caps) != set(RESOURCES)
            or any(
                type(requested_caps[key]) is not int or not 0 <= requested_caps[key] <= primary[key]
                for key in RESOURCES
            )
            or requested_caps["compute_seconds"] <= 0
        ):
            rejected.append(
                {
                    "option_id": "review-" + digest(alt)[:20],
                    "title": alt["title"],
                    "evidence_refs": alt["evidence_refs"],
                    "feasible": False,
                    "reason": "alternative_exceeds_original_task_reservation",
                    "forecast": {"status": "unknown_not_executable"},
                }
            )
            continue
        normalized_tasks.add(normalized)
        candidate = {
            **primary,
            **(requested_caps or {}),
            "opportunity_id": "option-" + digest([primary["opportunity_id"], alt])[:24],
            "title": alt["title"],
            "task": task,
            "source_refs": alt["evidence_refs"],
            "execution_binding": {},
        }
        try:
            candidate = freeze_execution(owner, Opportunity.model_validate(candidate).model_dump())
        except (PortfolioError, ValueError):
            rejected.append(
                {
                    "option_id": candidate["opportunity_id"],
                    "title": alt["title"],
                    "evidence_refs": alt["evidence_refs"],
                    "feasible": False,
                    "reason": "original_execution_contract_rejected",
                    "forecast": {"status": "unknown_not_executable"},
                }
            )
            continue
        candidates.append(candidate)
    feasible: list[dict[str, Any]] = []
    for candidate in candidates:
        # Positive probe weights are feasibility only, never a predicted probability.
        admitted = (
            bool(candidate.get("execution_binding"))
            and not candidate.get("depends_on")
            and _date(effective["expires_at"]) > now
            and effective["compute_seconds"] > 0
            and effective["max_parallel"] > 0
            and candidate["risk"] != "high"
            and all(candidate[key] <= effective[key] for key in RESOURCES)
            and candidate["opportunity_id"]
            in optimize_portfolio(
                [{**candidate, "value_score": 1, "confidence_bps": 1}],
                effective,
                max_selected=1,
            )["selected"]
        )
        treatment = treatment_id(candidate)
        predicted = (
            forecast(historical.get(treatment, []))
            if admitted
            else {"status": "unknown_infeasible"}
        )
        options.append(
            {
                "option_id": candidate["opportunity_id"],
                "title": candidate["title"],
                "task": candidate["task"],
                "evidence_refs": candidate["source_refs"],
                "treatment_sha256": treatment,
                "execution_sha256": digest(candidate),
                "evaluation_target": candidate.get("hypothesis"),
                "feasible": admitted,
                "reason": (
                    "solver_capacity_and_execution_contract" if admitted else "capacity_or_risk"
                ),
                "reservation_cap": {key: candidate[key] for key in RESOURCES},
                "reservation_basis": "hard_caps_not_cost_estimate",
                "execution_binding_sha256": digest(candidate.get("execution_binding") or {}),
                "policy_risk": candidate["risk"],
                "forecast": predicted,
            }
        )
        if admitted:
            feasible.append(candidate)
    # All action alternatives use the same target. Prefer a stronger verified
    # historical probability only when EVERY feasible action has such evidence.
    # Unknown counterfactual and other risks still require the original human approval.
    known = {
        row["option_id"]: row["forecast"]
        for row in options
        if row.get("feasible")
        and row["forecast"].get("status") == "historical_constant_rate_temporally_checked"
    }
    selected = feasible[:1]
    ranking = "unranked_experiment_for_human_review"
    if feasible and len(known) == len(feasible):
        selected = [
            max(
                feasible,
                key=lambda item: (
                    known[item["opportunity_id"]]["probability_of_target"],
                    -known[item["opportunity_id"]]["expected_accrued_cost_cents"],
                ),
            )
        ]
        ranking = "historical_target_rate_not_comparison_to_counterfactual"
    if not selected:
        ranking = "no_action_no_feasible_option"
    review = {
        "schema": "xcagi.xiaoc_decision_review/v1",
        "request_sha256": request_sha256,
        "frozen_at": now.isoformat(),
        "context_sha256": context_sha256,
        "evidence_refs": evidence_refs,
        "capacity_at_review": {
            key: effective[key] for key in (*RESOURCES, "max_parallel", "stop_loss_cents")
        },
        "capacity_constraint": "remaining_company_and_original_caps_with_stop_loss",
        "capacity_basis": (
            "company_remaining_at_review" if capacity is not None else "proposal_caps_only"
        ),
        "options": options + rejected,
        "selected_for_approval": selected[0]["opportunity_id"] if selected else "no_action",
        "selection_basis": ranking,
        "authority": "existing_portfolio_approval_required",
    }
    return review, selected


def evaluate_review(
    proposal: dict[str, Any], state: dict[str, Any], now: datetime
) -> dict[str, Any] | None:
    review = proposal.get("decision_review")
    if not isinstance(review, dict) or digest(proposal_content(proposal)) != proposal.get(
        "proposal_sha256"
    ):
        return None
    authorization = state.get("authorization", {})
    if (
        authorization.get("user_id") != proposal["owner_user_id"]
        or not authorization.get("actor")
        or authorization.get("proposal_sha256") != proposal["proposal_sha256"]
    ):
        return None
    selected = review.get("selected_for_approval")
    option = next((row for row in review["options"] if row["option_id"] == selected), None)
    item = next(
        (row for row in proposal["opportunities"] if row["opportunity_id"] == selected), None
    )
    if not option or not item or option["execution_sha256"] != digest(item):
        return None
    sample = closed_sample(item, state, now)
    if not sample:
        return {"status": "pending_or_unknown_independent_measurement", "option_id": selected}
    # A forecast recorded after approval or execution is not an out-of-sample
    # prediction, even if the mutable SQL result later contains a valid receipt.
    try:
        frozen_at = _date(review["frozen_at"])
        approved_at = _date(authorization["approved_at"])
        started_at = _date(state["tasks"][selected]["started_at"])
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    # A forecast captured at the approval instant is not verifiably pre-decision.
    if not frozen_at < approved_at <= started_at <= now:
        return {"status": "unscorable_prediction_timing", "option_id": selected}
    expected = option["forecast"]
    p = expected.get("probability_of_target")
    value = expected.get("expected_metric_value")
    cost = expected.get("expected_accrued_cost_cents")
    if (
        any(
            number is not None and (type(number) not in (int, float) or not math.isfinite(number))
            for number in (p, value, cost)
        )
        or (p is not None and not 0 <= p <= 1)
        or (cost is not None and cost < 0)
    ):
        return {"status": "unscorable_invalid_frozen_forecast", "option_id": selected}
    return {
        "status": "independent_measurement_verified",
        "option_id": selected,
        "snapshot_sha256": sample["snapshot_sha256"],
        "metric_evidence_sha256": sample["evidence_sha256"],
        "execution_result_sha256": sample["result_sha256"],
        "metric_id": item["hypothesis"]["metric_id"],
        "window_start": sample["window_start"],
        "window_end": sample["window_end"],
        "actual_metric_value": sample["value"],
        "actual_accrued_cost_cents": sample["accrued_cost_cents"],
        "cost_basis": sample["cost_basis"],
        "predicted_accrued_cost_cents": cost,
        "cost_error_cents": sample["accrued_cost_cents"] - cost if cost is not None else None,
        "absolute_cost_error_cents": (
            abs(sample["accrued_cost_cents"] - cost) if cost is not None else None
        ),
        "prediction_frozen_at": frozen_at.isoformat(),
        "counterfactual_status": "unknown_no_matched_control",
        "verification_scope": "original_ledger_snapshot_and_settlement_not_fresh_source_replay",
        "hit": sample["hit"],
        "predicted_probability": p,
        "predicted_metric_value": value,
        "brier": (p - sample["hit"]) ** 2 if p is not None else None,
        "metric_error": sample["value"] - value if value is not None else None,
        "absolute_metric_error": abs(sample["value"] - value) if value is not None else None,
        "forecast_status": expected["status"],
    }


def decision_quality_report(owner_user_id: int, *, as_of: datetime | None = None) -> dict[str, Any]:
    """Read-only forecast-error audit from original approved, settled SQL receipts.

    This is descriptive verification, not a causal business impact estimate or
    permission to change goals. It never scores an unknown or late prediction.
    """
    if type(owner_user_id) is not int or owner_user_id <= 0:
        raise PortfolioError("a valid decision owner is required")
    moment = as_of or datetime.now(UTC)
    if moment.tzinfo is None:
        raise PortfolioError("quality report requires a timezone-aware cutoff")
    moment = moment.astimezone(UTC)
    reviews = measured = scored = missing = rejected = duplicate = 0
    briers: list[float] = []
    monetary_errors: list[float] = []
    metric_errors: dict[str, list[float]] = {}
    seen_evidence: set[tuple[str, str]] = set()
    sample_refs: list[str] = []
    with get_session_factory()() as session:
        rows = session.scalars(
            select(StrategicDecision)
            .where(
                StrategicDecision.scope == "strategy_portfolio",
                StrategicDecision.scope_ref.like(f"user:{owner_user_id}:%"),
                StrategicDecision.proposed_at <= moment,
            )
            .order_by(StrategicDecision.updated_at.desc(), StrategicDecision.id.desc())
            .limit(HISTORY_LIMIT)
        )
        for row in rows:
            if row.decided_by not in {"user", "council-vote"}:
                continue
            try:
                proposal = json.loads(cast("str | None", row.decision_payload_json) or "{}")
                state = json.loads(cast("str | None", row.execution_result_json) or "{}")
                if (
                    not isinstance(proposal, dict)
                    or not isinstance(state, dict)
                    or proposal.get("schema") != SCHEMA
                    or proposal.get("owner_user_id") != owner_user_id
                    or not isinstance(proposal.get("decision_review"), dict)
                ):
                    continue
                reviews += 1
                evaluation = evaluate_review(proposal, state, moment)
            except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
                rejected += 1
                continue
            if evaluation is None or evaluation["status"].startswith("unscorable_"):
                rejected += 1
                continue
            if evaluation["status"] != "independent_measurement_verified":
                missing += 1
                continue
            evidence_key = (
                evaluation["metric_id"],
                evaluation["metric_evidence_sha256"],
            )
            if evidence_key in seen_evidence:
                duplicate += 1
                continue
            seen_evidence.add(evidence_key)
            measured += 1
            sample_refs.append(evaluation["snapshot_sha256"])
            brier = evaluation["brier"]
            if brier is None:
                continue
            scored += 1
            briers.append(brier)
            cost_error = evaluation["absolute_cost_error_cents"]
            if cost_error is not None:
                monetary_errors.append(cost_error)
            metric_error = evaluation["absolute_metric_error"]
            if metric_error is not None:
                metric_errors.setdefault(evaluation["metric_id"], []).append(metric_error)
    return {
        "schema": "xcagi.xiaoc_decision_quality/v1",
        "owner_user_id": owner_user_id,
        "as_of": moment.isoformat(),
        "history_limit": HISTORY_LIMIT,
        "reviewed_count": reviews,
        "independently_measured_count": measured,
        "scorable_probability_count": scored,
        "unknown_or_pending_count": missing,
        "invalid_or_late_count": rejected,
        "duplicate_evidence_count": duplicate,
        "status": (
            "descriptive_observed_forecast_error_only"
            if scored >= MIN_SAMPLES
            else "unknown_insufficient_real_scored_predictions"
        ),
        "mean_brier": mean(briers) if briers else None,
        "mean_absolute_accrued_cost_error_cents": (
            mean(monetary_errors) if monetary_errors else None
        ),
        "mean_absolute_metric_error_by_metric": {
            key: mean(values) for key, values in sorted(metric_errors.items())
        },
        "original_snapshot_refs": sample_refs,
        "limitation": (
            "Approved historical predictions and independently recorded measurements "
            "only; no unobserved counterfactual, causal profit, or autonomous L6 proof."
        ),
    }
