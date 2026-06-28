from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.external_advantage_ci_regression import build_external_advantage_ci_regression
from retort_engine.service import RetortService


def test_external_advantage_ci_regression_replays_all_cases_with_blind_delta(tmp_path: Path) -> None:
    result = build_external_advantage_ci_regression(tmp_path)

    assert result["status"] == "ready"
    assert result["summary"]["case_count"] == 6
    assert result["summary"]["passed_case_count"] == 6
    assert result["summary"]["blind_delta_floor"] == 80
    assert result["summary"]["blind_delta_floor_met"] is True
    assert result["summary"]["all_direct_review_regressions_verified"] is True
    assert result["summary"]["all_cases_have_ci_acceptance"] is True
    assert validate_contract("external_advantage_ci_regression_result", result)["valid"] is True


def test_service_exposes_external_advantage_ci_regression(tmp_path: Path) -> None:
    result = RetortService().external_advantage_ci_regression({"project": str(tmp_path)})

    assert result["status"] == "ready"
    assert result["summary"]["source_project_count"] == 6


def test_external_advantage_ci_regression_cli_outputs_contract(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "retort_engine.cli", "external-advantage-ci-regression", "--project", str(tmp_path), "--json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert validate_contract("external_advantage_ci_regression_result", payload)["valid"] is True
    assert payload["summary"]["blind_delta_floor_met"] is True
