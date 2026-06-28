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
    assert result["summary"]["ready_decision_count"] == 4
    assert result["summary"]["core_decision_path_count"] == 4
    assert result["summary"]["all_core_decisions_ready"] is True
    assert validate_contract("absorption_release_decision_result", result)["valid"] is True


def test_service_exposes_absorption_release_decision(tmp_path: Path) -> None:
    _write_decision_inputs(tmp_path)

    result = RetortService().absorption_release_decision({"project": str(tmp_path)})

    assert result["status"] == "ready"


def _write_decision_inputs(root: Path) -> None:
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    fixtures = {
        "retort_quality_gate_bundle.json": {"status": "ready", "summary": {"all_gates_passed": True}},
        "retort_absorption_continuity_probe.json": {"status": "ready", "summary": {}},
        "retort_pr_long_run_review.json": {"status": "ready", "summary": {}},
        "retort_production_recovery_drill.json": {"status": "ready", "summary": {}},
        "retort_employee_patch_closure.json": {"status": "ready", "summary": {"all_expected_outcomes_verified": True}},
        "retort_review_quality_benchmark.json": {"status": "ready", "summary": {"post_absorption_score_delta": 10}},
    }
    for name, payload in fixtures.items():
        (docs / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
