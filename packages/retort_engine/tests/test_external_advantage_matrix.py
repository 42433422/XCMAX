from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.external_advantage_matrix import build_external_advantage_matrix
from retort_engine.service import RetortService


def test_external_advantage_matrix_compares_baseline_to_current_behavior(tmp_path: Path) -> None:
    result = build_external_advantage_matrix(tmp_path)

    assert result["status"] == "ready"
    assert result["summary"]["case_count"] >= 6
    assert result["summary"]["ready_case_count"] == result["summary"]["case_count"]
    assert result["summary"]["source_project_count"] >= 5
    assert result["summary"]["absorbed_signal_count"] >= 6
    assert result["summary"]["score_delta"] >= 35
    assert result["summary"]["per_case_before_after"] is True
    assert result["summary"]["all_advantages_improved"] is True
    assert result["summary"]["all_delta_regressions_verified"] is True
    assert result["summary"]["passed_regression_case_count"] == result["summary"]["case_count"]
    assert all(row["retort"]["score"] > row["baseline"]["score"] for row in result["matrix"])
    assert all(row["retort"]["publishable_comment_count"] > 0 for row in result["matrix"])
    assert validate_contract("external_advantage_matrix_result", result)["valid"] is True


def test_external_advantage_matrix_writes_report(tmp_path: Path) -> None:
    output = tmp_path / "docs" / "retort_external_advantage_matrix.json"

    result = build_external_advantage_matrix(tmp_path, output=output)
    saved = json.loads(output.read_text(encoding="utf-8"))

    assert result["status"] == "ready"
    assert saved["summary"]["score_delta"] == result["summary"]["score_delta"]


def test_external_advantage_matrix_service_surface(tmp_path: Path) -> None:
    result = RetortService().external_advantage_matrix({"project": str(tmp_path)})

    assert result["status"] == "ready"
    assert result["summary"]["ready_case_count"] >= 6


def test_external_advantage_matrix_cli_outputs_contract(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "retort_engine.cli",
            "external-advantage-matrix",
            "--project",
            str(tmp_path),
            "--json",
        ],
        check=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(result.stdout)

    assert payload["status"] == "ready"
    assert validate_contract("external_advantage_matrix_result", payload)["valid"] is True
