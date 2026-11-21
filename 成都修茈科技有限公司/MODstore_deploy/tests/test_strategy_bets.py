"""Imported bet evidence stays readable; executable authority lives in SQL."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from modstore_server import strategic_portfolio as portfolio
from modstore_server import strategic_portfolio_runtime as runtime
from modstore_server import strategic_portfolio_usage as usage
from modstore_server import strategy_bets
from tests.test_strategic_portfolio import database as database
from tests.test_strategic_portfolio import limits, opportunity, proposal


def _historical_bet(**overrides):
    return {
        "bet_id": "bet-onboarding",
        "title": "新手引导提效",
        "hypothesis": "引导改造能把意图准确率拉起来",
        "metric_id": "intent_accuracy",
        "threshold": 0.85,
        "direction": "max",
        "window_days": 14,
        "kill_criteria": ["两周内准确率无提升"],
        "budget": {"proposals": 2, "tokens": 1000, "ci_minutes": 10, "human_hours": 1},
        "review_at": (datetime.now(UTC) + timedelta(days=14)).isoformat(),
        **overrides,
    }


def _hypothesis(**overrides):
    bet = _historical_bet(**overrides)
    return {key: bet[key] for key in strategy_bets.BetHypothesis.model_fields if key in bet}


@pytest.fixture(autouse=True)
def _ledger(tmp_path, monkeypatch):
    path = tmp_path / "evolution_decisions.jsonl"
    monkeypatch.setenv("MODSTORE_EVOLUTION_LEDGER_PATH", str(path))
    return path


def _write_imported(path, *, bet=None, spent=0, outcome=None):
    """Historical fixture creation is deliberately separate from production writers."""
    rows = [{"event_type": strategy_bets.REGISTERED, "bet": bet or _historical_bet()}]
    if spent:
        rows.append(
            {"event_type": strategy_bets.SPEND, "bet_id": "bet-onboarding", "proposals": spent}
        )
    if outcome:
        rows.append({"event_type": strategy_bets.OUTCOME, "bet_id": "bet-onboarding", **outcome})
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path.read_bytes()


def _completed_sql_bet(database, monkeypatch):
    decision_id = proposal(database, rows=[opportunity(hypothesis=_hypothesis())])
    portfolio.plan_portfolio(decision_id)
    task = runtime._claim(decision_id, 7)
    runtime._finish(task, {"ok": True, "status": "completed"}, 1)
    start = datetime.now(UTC) - timedelta(days=15)
    portfolio.mutate_portfolio(
        decision_id,
        lambda _row, _proposal, state, _db: state["tasks"]["a"].update(
            started_at=start.isoformat()
        ),
    )
    monkeypatch.setattr(
        runtime, "_business_outcome", lambda _: {"status": "unknown", "revenue_cents": None}
    )
    return decision_id, start


def test_registration_is_idempotent_and_hashed_in_sql(database, _ledger):
    caps = limits()
    first = proposal(
        database, rows=[opportunity(hypothesis=_hypothesis())], caps=caps, approved=False
    )
    second = proposal(
        database, rows=[opportunity(hypothesis=_hypothesis())], caps=caps, approved=False
    )
    assert first == second
    stored = portfolio.portfolio_status(first, owner_user_id=7)
    assert stored["status"] == "proposed" and len(stored["proposal_sha256"]) == 64
    with pytest.raises(portfolio.PortfolioError):
        portfolio.plan_portfolio(first)
    portfolio.authorize_portfolio(
        first, owner_user_id=7, actor="admin:7", expected_proposal_sha256=stored["proposal_sha256"]
    )
    portfolio.plan_portfolio(first)
    assert portfolio.portfolio_status(first)["status"] == "executing"
    assert not _ledger.exists()


def test_legacy_register_cannot_create_authority(_ledger):
    with pytest.raises(ValueError, match="authenticated approval"):
        strategy_bets.register_bet(**_historical_bet())
    assert not _ledger.exists()


def test_hypothesis_rejects_unknown_metric():
    with pytest.raises(ValueError, match="unsupported strategy metric"):
        strategy_bets.BetHypothesis.model_validate(_hypothesis(metric_id="does_not_exist"))


@pytest.mark.parametrize("requested", [1, 3])
def test_legacy_spend_rejected_within_and_over_imported_budget(_ledger, requested):
    original = _write_imported(_ledger)
    with pytest.raises(strategy_bets.BudgetExceeded, match="reserved and settled"):
        strategy_bets.record_spend("bet-onboarding", proposals=requested)
    assert _ledger.read_bytes() == original
    assert strategy_bets.bet_state("bet-onboarding")["spent"]["proposals"] == 0


def test_sql_task_budget_blocks_second_paid_call_before_dispatch(database):
    decision_id = proposal(database, rows=[opportunity(cost_cents=1)])
    portfolio.plan_portfolio(decision_id)
    task = runtime._claim(decision_id, 7)
    with usage.portfolio_usage_scope(decision_id, "a", task["lease_token"]):
        assert usage.prepare_platform_call("test", "model", [], 20)
        with pytest.raises(portfolio.PortfolioError, match="budget"):
            usage.prepare_platform_call("test", "model", [], 20)
    assert len(portfolio.portfolio_status(decision_id)["tasks"]["a"]["calls"]) == 1


def test_judge_three_states():
    assert strategy_bets.judge("intent_accuracy", 0.9, 0.85, "max") == "hit"
    assert strategy_bets.judge("intent_accuracy", 0.5, 0.85, "max") == "miss"
    assert strategy_bets.judge("intent_accuracy", None, 0.85, "max") == "inconclusive"


def test_due_sql_review_records_in_window_report_and_freezes_snapshot(
    database, tmp_path, monkeypatch, _ledger
):
    decision_id, start = _completed_sql_bet(database, monkeypatch)
    report = tmp_path / "intent.json"
    report.write_text(
        json.dumps({"accuracy": 0.91, "generated_at": (start + timedelta(days=7)).isoformat()}),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODSTORE_INTENT_REPORT_PATH", str(report))
    reviewed = runtime.review_portfolio(decision_id)["hypotheses"][0]
    assert reviewed["verdict"] == "hit" and reviewed["evidence"]["value"] == pytest.approx(0.91)
    report.write_text(
        json.dumps({"accuracy": 0.1, "generated_at": datetime.now(UTC).isoformat()}),
        encoding="utf-8",
    )
    assert runtime.review_portfolio(decision_id)["hypotheses"][0] == reviewed
    assert not _ledger.exists()


def test_sql_review_without_evidence_is_inconclusive(database, tmp_path, monkeypatch):
    decision_id, _start = _completed_sql_bet(database, monkeypatch)
    monkeypatch.setenv("MODSTORE_INTENT_REPORT_PATH", str(tmp_path / "missing.json"))
    reviewed = runtime.review_portfolio(decision_id)["hypotheses"][0]
    assert reviewed["verdict"] == "inconclusive"
    assert reviewed["evidence"]["reason"] == "metric_source_unavailable"


def test_legacy_review_reads_frozen_outcome_without_rewriting_or_claiming_source_verification(
    tmp_path, monkeypatch, _ledger
):
    original = _write_imported(_ledger, outcome={"verdict": "hit", "value": 0.91})
    report = tmp_path / "intent.json"
    report.write_text(json.dumps({"accuracy": 0.10}), encoding="utf-8")
    monkeypatch.setenv("MODSTORE_INTENT_REPORT_PATH", str(report))
    reviewed = strategy_bets.review_due(now=datetime.now(UTC) + timedelta(days=15))
    assert reviewed[0]["verdict"] == "hit" and reviewed[0]["value"] == 0.91
    assert strategy_bets.audit_outcomes() == {
        "calculation_verified": 1,
        "source_evidence_verified": 0,
    }
    assert strategy_bets.run_review()["legacy_read_only"] is True
    assert _ledger.read_bytes() == original


def test_legacy_audit_detects_wrong_recorded_threshold_without_new_evidence_claim(_ledger):
    original = _write_imported(_ledger, outcome={"verdict": "hit", "value": 0.10})
    assert strategy_bets.audit_outcomes() == {
        "calculation_verified": 0,
        "source_evidence_verified": 0,
    }
    assert _ledger.read_bytes() == original


def test_read_intent_accuracy_from_rule_counts(tmp_path, monkeypatch):
    report = tmp_path / "intent.json"
    report.write_text(
        json.dumps(
            {
                "rule": {
                    "counts": {
                        "core": {"correct": 24, "total": 24},
                        "semantic": {"correct": 60, "total": 73},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODSTORE_INTENT_REPORT_PATH", str(report))
    assert strategy_bets.read_metric("intent_accuracy") == pytest.approx(84 / 97)


def test_read_domain_rated_ratio(tmp_path, monkeypatch):
    audit = tmp_path / "domains.json"
    audit.write_text(
        json.dumps({"domains": [{"status": "RATED"}, {"status": "UNRATED"}]}), encoding="utf-8"
    )
    monkeypatch.setenv("MODSTORE_DOMAIN_AUDIT_PATH", str(audit))
    assert strategy_bets.read_metric(strategy_bets.DOMAIN_METRIC) == pytest.approx(0.5)


@pytest.mark.parametrize(
    "expired,spent,outcome,active",
    [
        (False, 0, None, True),
        (True, 0, None, False),
        (False, 2, None, False),
        (False, 0, {"verdict": "hit", "value": 0.9}, False),
    ],
)
def test_legacy_expired_exhausted_or_reviewed_bet_is_not_active(
    _ledger, expired, spent, outcome, active
):
    bet = _historical_bet(
        review_at=(datetime.now(UTC) + timedelta(days=-1 if expired else 14)).isoformat()
    )
    original = _write_imported(_ledger, bet=bet, spent=spent, outcome=outcome)
    assert strategy_bets.active_bet_id() == ("bet-onboarding" if active else "")
    assert _ledger.read_bytes() == original
