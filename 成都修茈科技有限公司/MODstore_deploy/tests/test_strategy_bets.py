import json
from datetime import datetime, timedelta, timezone

import pytest

from modstore_server import strategy_bets


def _register(**overrides):
    payload = {
        "bet_id": "bet-onboarding",
        "title": "新手引导提效",
        "hypothesis": "引导改造能把七日留存拉起来",
        "metric_id": "intent_accuracy",
        "threshold": 0.85,
        "direction": "max",
        "window_days": 14,
        "kill_criteria": ["两周内准确率无提升"],
        "budget": {"proposals": 2, "tokens": 1000, "ci_minutes": 10, "human_hours": 1},
    }
    payload.update(overrides)
    return strategy_bets.register_bet(**payload)


@pytest.fixture(autouse=True)
def _ledger(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MODSTORE_EVOLUTION_LEDGER_PATH", str(tmp_path / "evolution_decisions.jsonl")
    )
    return tmp_path


def test_register_is_idempotent_and_hashed():
    first = _register()
    second = _register()
    assert first["bet_id"] == second["bet_id"]
    assert first["payload_sha256"] == second["payload_sha256"]
    assert len(first["payload_sha256"]) == 64


def test_register_rejects_unknown_metric():
    with pytest.raises(ValueError):
        _register(metric_id="does_not_exist")


def test_spend_over_budget_is_rejected():
    _register()
    strategy_bets.record_spend("bet-onboarding", proposals=2)
    with pytest.raises(strategy_bets.BudgetExceeded):
        strategy_bets.record_spend("bet-onboarding", proposals=1)


def test_judge_three_states():
    assert strategy_bets.judge("intent_accuracy", 0.9, 0.85, "max") == "hit"
    assert strategy_bets.judge("intent_accuracy", 0.5, 0.85, "max") == "miss"
    assert strategy_bets.judge("intent_accuracy", None, 0.85, "max") == "inconclusive"


def test_review_due_reads_report_and_records_hit(tmp_path, monkeypatch):
    report = tmp_path / "intent.json"
    report.write_text(json.dumps({"accuracy": 0.91}), encoding="utf-8")
    monkeypatch.setenv("MODSTORE_INTENT_REPORT_PATH", str(report))
    _register()

    future = datetime.now(timezone.utc) + timedelta(days=15)
    reviewed = strategy_bets.review_due(now=future)

    assert [item["verdict"] for item in reviewed] == ["hit"]
    assert reviewed[0]["value"] == pytest.approx(0.91)


def test_review_due_without_evidence_is_inconclusive(monkeypatch):
    monkeypatch.delenv("MODSTORE_INTENT_REPORT_PATH", raising=False)
    _register()

    future = datetime.now(timezone.utc) + timedelta(days=15)
    reviewed = strategy_bets.review_due(now=future)

    assert reviewed[0]["verdict"] == "inconclusive"
    assert reviewed[0]["reason"] == "evidence_missing"


def test_audit_flags_mismatch_after_evidence_changes(tmp_path, monkeypatch):
    report = tmp_path / "intent.json"
    report.write_text(json.dumps({"accuracy": 0.91}), encoding="utf-8")
    monkeypatch.setenv("MODSTORE_INTENT_REPORT_PATH", str(report))
    _register()

    future = datetime.now(timezone.utc) + timedelta(days=15)
    strategy_bets.review_due(now=future)

    report.write_text(json.dumps({"accuracy": 0.10}), encoding="utf-8")
    assert strategy_bets.audit_outcomes() == {"verified": 0, "mismatched": 1}


def test_expired_or_exhausted_bet_is_not_active():
    _register()
    assert strategy_bets.active_bet_id() == "bet-onboarding"

    strategy_bets.record_spend("bet-onboarding", proposals=2)
    assert strategy_bets.active_bet_id() == ""
