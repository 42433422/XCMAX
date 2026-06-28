from __future__ import annotations

import json
from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.production_recovery_drill import build_production_recovery_drill
from retort_engine.service import RetortService


def test_production_recovery_drill_requires_all_faults_recovered(tmp_path: Path) -> None:
    _write_recovery_inputs(tmp_path)

    result = build_production_recovery_drill(tmp_path)

    assert result["status"] == "ready"
    assert result["summary"]["all_recovered"] is True
    assert result["summary"]["real_network_denial_verified"] is True
    assert result["summary"]["live_write_rollback_verified"] is True
    assert result["summary"]["recovered_count"] == 6
    assert validate_contract("production_recovery_drill_result", result)["valid"] is True


def test_service_exposes_production_recovery_drill(tmp_path: Path) -> None:
    _write_recovery_inputs(tmp_path)

    result = RetortService().production_recovery_drill({"project": str(tmp_path)})

    assert result["status"] == "ready"


def _write_recovery_inputs(root: Path) -> None:
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "retort_pr_live_publish_probe.json").write_text(
        json.dumps({"status": "live_rolled_back", "summary": {"live_github_write": True, "rollback_verified": True}, "evidence": {"real_network": True}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (docs / "retort_pr_readonly_degradation_probe.json").write_text(
        json.dumps({"status": "read_only_degraded", "summary": {"degraded_without_write": True, "rollback_verified": True}, "evidence": {"real_network": True}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (docs / "retort_pr_low_permission_probe.json").write_text(
        json.dumps({"status": "permission_denied_degraded", "summary": {"permission_denied": True, "degraded_without_write": True, "rollback_verified": True}, "evidence": {"real_network": True}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (docs / "retort_pr_publish_sandbox.json").write_text(
        json.dumps({"status": "sandbox_rolled_back", "summary": {"created_comment_count": 1, "rollback_verified": True}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (docs / "retort_employee_patch_closure.json").write_text(
        json.dumps({"status": "ready", "summary": {"all_expected_outcomes_verified": True, "unexpected_gate_failure_count": 0, "failure_case_rolled_back": True}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (docs / "retort_quality_gate_bundle.json").write_text(
        json.dumps({"status": "ready", "summary": {"all_gates_passed": True}}, ensure_ascii=False),
        encoding="utf-8",
    )
