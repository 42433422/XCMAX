from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from retort_engine.competitor_behavior_regression import build_competitor_behavior_regression
from retort_engine.contracts import validate_contract
from retort_engine.service import RetortService


def test_competitor_behavior_regression_turns_competitor_signals_into_review_diff_assertions(tmp_path: Path) -> None:
    result = build_competitor_behavior_regression(tmp_path)

    assert result["status"] == "ready"
    assert result["summary"]["ready_case_count"] == 3
    assert result["summary"]["source_project_count"] == 3
    assert result["summary"]["all_cases_direct_review_execution"] is True
    assert result["summary"]["all_competitor_signals_regressed"] is True
    assert result["summary"]["behavior_assertion_count"] >= 18
    assert all(case["publishable_comment_count"] > 0 for case in result["cases"])
    assert validate_contract("competitor_behavior_regression_result", result)["valid"] is True


def test_service_exposes_competitor_behavior_regression(tmp_path: Path) -> None:
    result = RetortService().competitor_behavior_regression({"project": str(tmp_path)})

    assert result["status"] == "ready"
    assert result["summary"]["all_competitor_signals_regressed"] is True


def test_competitor_behavior_regression_cli_outputs_contract(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "retort_engine.cli", "competitor-behavior-regression", "--project", str(tmp_path), "--json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert validate_contract("competitor_behavior_regression_result", payload)["valid"] is True
    assert payload["summary"]["ready_case_count"] == 3
