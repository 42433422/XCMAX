from __future__ import annotations

import json
from pathlib import Path

from retort_engine.absorption_release_decision import build_absorption_release_decision
from retort_engine.contracts import validate_contract
from retort_engine.service import RetortService


def test_absorption_release_decision_combines_core_product_gates(tmp_path: Path) -> None:
    _write_decision_inputs(tmp_path)

    result = build_absorption_release_decision(tmp_path)

    assert result["status"] == "ready"
    assert result["summary"]["ready_decision_count"] == 7
    assert result["summary"]["core_decision_path_count"] == 6
    assert result["summary"]["all_core_decisions_ready"] is True
    assert result["summary"]["holdout_blind_eval_ready"] is True
    assert result["summary"]["failure_rollback_ready"] is True
    assert result["summary"]["operator_journey_ready"] is True
    assert validate_contract("absorption_release_decision_result", result)["valid"] is True


def test_service_exposes_absorption_release_decision(tmp_path: Path) -> None:
    _write_decision_inputs(tmp_path)

    result = RetortService().absorption_release_decision({"project": str(tmp_path)})

    assert result["status"] == "ready"


def test_absorption_release_decision_blocks_without_holdout_quality(tmp_path: Path) -> None:
    _write_decision_inputs(tmp_path)
    (tmp_path / "docs" / "retort_pr_holdout_blind_eval.json").unlink()

    result = build_absorption_release_decision(tmp_path)

    assert result["status"] == "blocked"
    assert result["summary"]["holdout_blind_eval_ready"] is False
    assert result["summary"]["blocking_decision_count"] == 1
    assert any(decision["name"] == "accept_blind_holdout_quality" and decision["action"] == "block" for decision in result["decisions"])


def test_absorption_release_decision_blocks_without_operator_journey(tmp_path: Path) -> None:
    _write_decision_inputs(tmp_path)
    (tmp_path / "docs" / "retort_operator_journey_replay.json").unlink()

    result = build_absorption_release_decision(tmp_path)

    assert result["status"] == "blocked"
    assert result["summary"]["operator_journey_ready"] is False
    assert result["summary"]["blocking_decision_count"] == 1
    assert any(decision["name"] == "replay_operator_absorption_journey" and decision["action"] == "block" for decision in result["decisions"])


def _write_decision_inputs(root: Path) -> None:
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    fixtures = {
        "retort_quality_gate_bundle.json": {"status": "ready", "summary": {"all_gates_passed": True}},
        "retort_absorption_continuity_probe.json": {"status": "ready", "summary": {}},
        "retort_pr_long_run_review.json": {"status": "ready", "summary": {}},
        "retort_pr_holdout_blind_eval.json": {"status": "ready", "summary": {"accepted_pr_count": 20, "target_pr_count": 20}},
        "retort_pr_failure_rollback_replay.json": {"status": "ready", "summary": {"all_failures_rolled_back": True}},
        "retort_production_recovery_drill.json": {"status": "ready", "summary": {}},
        "retort_employee_patch_closure.json": {"status": "ready", "summary": {"all_expected_outcomes_verified": True}},
        "retort_review_quality_benchmark.json": {"status": "ready", "summary": {"post_absorption_score_delta": 10}},
        "retort_operator_journey_replay.json": {"status": "ready", "summary": {"cross_domain_live_probe_ready": True}},
    }
    for name, payload in fixtures.items():
        (docs / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
