"""Decision prediction timing and independently recorded quality audit."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from modstore_server import business_decision_review as review
from modstore_server.db.strategic import StrategicDecision
from modstore_server.strategic_portfolio import digest
from tests.test_strategic_portfolio import database


def _example(*, frozen_after_start: bool = False, probability: float | None = 0.25):
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=1)
    hypothesis = {
        "hypothesis": "Check reported availability",
        "metric_id": "slo_availability",
        "threshold": 0.7,
        "direction": "max",
        "window_days": 1,
        "kill_criteria": ["miss"],
    }
    item = {"opportunity_id": "op-1", "hypothesis": hypothesis}
    evidence = {
        "value": 0.8,
        "source": "slo-report",
        "observed_at": end.isoformat(),
        "evidence_sha256": digest("independent-report"),
    }
    snapshot = {
        "opportunity_id": item["opportunity_id"],
        "hypothesis": hypothesis,
        "evidence": evidence,
        "verdict": "hit",
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "reviewed_at": end.isoformat(),
    }
    snapshot["snapshot_sha256"] = digest(snapshot)
    execution = {
        "status": "completed",
        "started_at": start.isoformat(),
        "completed_at": end.isoformat(),
        "result_sha256": digest("signed-execution-result"),
        "cost_basis": "approved_tariff_accrual",
        "accrued_cost_cents": 15,
        "calls": {
            "one": {
                "status": "settled",
                "cost_basis": "approved_tariff_accrual",
                "accrued_cost_cents": 15,
            }
        },
    }
    frozen = start + timedelta(hours=1) if frozen_after_start else start - timedelta(hours=2)
    decision_review = {
        "frozen_at": frozen.isoformat(),
        "selected_for_approval": item["opportunity_id"],
        "options": [
            {
                "option_id": item["opportunity_id"],
                "execution_sha256": digest(item),
                "forecast": {
                    "status": "historical_constant_rate_temporally_checked",
                    "probability_of_target": probability,
                    "expected_metric_value": 0.6,
                    "expected_accrued_cost_cents": 10,
                },
            }
        ],
    }
    proposal = {
        "schema": review.SCHEMA,
        "owner_user_id": 7,
        "goal": "Improve real availability",
        "period": "2025-Q1",
        "limits": {},
        "opportunities": [item],
        "decision_review": decision_review,
    }
    proposal["proposal_sha256"] = digest(review.proposal_content(proposal))
    state = {
        "authorization": {
            "actor": "admin:7",
            "user_id": 7,
            "approved_at": (start - timedelta(hours=1)).isoformat(),
            "proposal_sha256": proposal["proposal_sha256"],
        },
        "tasks": {"op-1": execution},
        "hypothesis_outcomes": {"op-1": snapshot},
    }
    return proposal, state, end + timedelta(days=1)


def test_post_hoc_prediction_is_not_scored_and_frozen_values_are_checked():
    proposal, state, as_of = _example()
    score = review.evaluate_review(proposal, state, as_of)
    assert score is not None
    assert score["status"] == "independent_measurement_verified"
    assert score["brier"] == pytest.approx(0.5625)
    assert score["absolute_cost_error_cents"] == 5
    assert score["absolute_metric_error"] == pytest.approx(0.2)
    assert score["prediction_frozen_at"] < state["tasks"]["op-1"]["started_at"]

    late_proposal, late_state, _ = _example(frozen_after_start=True)
    assert review.evaluate_review(late_proposal, late_state, as_of) == {
        "status": "unscorable_prediction_timing",
        "option_id": "op-1",
    }

    simultaneous_proposal, simultaneous_state, _ = _example()
    simultaneous_proposal["decision_review"]["frozen_at"] = simultaneous_state[
        "authorization"
    ]["approved_at"]
    simultaneous_proposal["proposal_sha256"] = digest(
        review.proposal_content(simultaneous_proposal)
    )
    simultaneous_state["authorization"]["proposal_sha256"] = simultaneous_proposal[
        "proposal_sha256"
    ]
    assert review.evaluate_review(simultaneous_proposal, simultaneous_state, as_of) == {
        "status": "unscorable_prediction_timing",
        "option_id": "op-1",
    }

    invalid_proposal, invalid_state, _ = _example(probability=1.2)
    assert review.evaluate_review(invalid_proposal, invalid_state, as_of) == {
        "status": "unscorable_invalid_frozen_forecast",
        "option_id": "op-1",
    }

    proposal["decision_review"]["options"][0]["forecast"]["probability_of_target"] = 0.9
    assert review.evaluate_review(proposal, state, as_of) is None


def _record(decision_id, proposal, state, *, scope_owner=7):
    return StrategicDecision(
        decision_id=decision_id,
        title="Original strategy review",
        scope="strategy_portfolio",
        scope_ref=f"user:{scope_owner}:2025-Q1",
        status="executing",
        decided_by="user",
        proposed_at=datetime(2024, 12, 30, tzinfo=UTC),
        decision_payload_json=json.dumps(proposal),
        execution_result_json=json.dumps(state),
    )


def test_quality_audit_deduplicates_sources_and_does_not_score_unknowns(database, monkeypatch):
    monkeypatch.setattr(review, "get_session_factory", lambda: database)
    proposal, state, as_of = _example()
    unknown_proposal, unknown_state, _ = _example(probability=None)
    # Independent source but no eligible numerical forecast: measured, not scored.
    evidence = unknown_state["hypothesis_outcomes"]["op-1"]["evidence"]
    evidence["evidence_sha256"] = digest("separate-source")
    snapshot = unknown_state["hypothesis_outcomes"]["op-1"]
    snapshot["snapshot_sha256"] = digest(
        {key: value for key, value in snapshot.items() if key != "snapshot_sha256"}
    )
    late_proposal, late_state, _ = _example(frozen_after_start=True)
    with database() as session:
        session.add_all(
            [
                _record("quality-1", proposal, state),
                _record("quality-2", proposal, state),
                _record("quality-3", unknown_proposal, unknown_state),
                _record("quality-4", late_proposal, late_state),
                _record("other-owner", proposal, state, scope_owner=8),
            ]
        )
        session.commit()
    result = review.decision_quality_report(7, as_of=as_of)
    assert result["reviewed_count"] == 4
    assert result["independently_measured_count"] == 2
    assert result["scorable_probability_count"] == 1
    assert result["duplicate_evidence_count"] == 1
    assert result["invalid_or_late_count"] == 1
    assert result["mean_brier"] == pytest.approx(0.5625)
    assert result["mean_absolute_accrued_cost_error_cents"] == 5
    assert result["mean_absolute_metric_error_by_metric"]["slo_availability"] == pytest.approx(
        0.2
    )
    assert result["status"] == "unknown_insufficient_real_scored_predictions"
    assert len(result["original_snapshot_refs"]) == 2
    assert review.decision_quality_report(8, as_of=as_of)["reviewed_count"] == 0
    assert review.decision_quality_report(7, as_of=as_of - timedelta(days=365))[
        "reviewed_count"
    ] == 0


def test_owner_scoped_quality_route_uses_authenticated_identity(monkeypatch):
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from modstore_server import strategic_portfolio_api

    calls = []
    monkeypatch.setattr(
        review,
        "decision_quality_report",
        lambda owner_user_id: calls.append(owner_user_id) or {"owner_user_id": owner_user_id},
    )
    app = FastAPI()
    app.include_router(strategic_portfolio_api.router)
    app.dependency_overrides[strategic_portfolio_api.require_admin] = lambda: SimpleNamespace(id=7)
    with TestClient(app) as client:
        response = client.get("/portfolios/quality")
        assert response.status_code == 200
        assert response.json() == {"owner_user_id": 7}
    assert calls == [7]



def test_due_time_does_not_score_future_business_measurement():
    proposal, state, as_of = _example()
    # The original result can be present in a ledger, but it is not a mature
    # independent measurement until the registered window actually closes.
    before_due = datetime.fromisoformat(
        state["hypothesis_outcomes"]["op-1"]["window_end"]
    ) - timedelta(seconds=1)
    assert before_due < as_of
    assert review.evaluate_review(proposal, state, before_due) == {
        "status": "pending_or_unknown_independent_measurement",
        "option_id": "op-1",
    }


def test_no_action_remains_feasible_when_every_executable_option_is_ineligible(
    database, monkeypatch
):
    from tests.test_strategic_portfolio import limits, opportunity

    monkeypatch.setattr(review, "get_session_factory", lambda: database)
    # No execution binding and high risk must not be silently converted into
    # a permission to execute. The explicit abstention has a zero reservation.
    primary = opportunity(
        "risk-blocked", risk="high", execution_binding={}, source_refs=["incident:1"]
    )
    decision, selected = review.compare_options(
        owner=7,
        primary=primary,
        limits=limits(max_parallel=1),
        alternatives=[],
        context_sha256=digest("frozen-context"),
        evidence_refs=["incident:1"],
        request_sha256=digest("request"),
    )
    abstain = decision["options"][0]
    assert abstain["option_id"] == "no_action"
    assert abstain["feasible"] is True
    assert abstain["reservation_cap"] == dict.fromkeys(review.RESOURCES, 0)
    assert abstain["forecast"]["status"] == "unknown_counterfactual_not_observed"
    assert abstain["forecast"]["direct_new_action_cost_cents"] == 0
    assert decision["selected_for_approval"] == "no_action"
    assert decision["selection_basis"] == "no_action_no_feasible_option"
    assert decision["authority"] == "existing_portfolio_approval_required"
    assert selected == []
