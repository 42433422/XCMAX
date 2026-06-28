from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.cross_domain_ci_regression import build_cross_domain_ci_regression
from retort_engine.service import RetortService


def test_cross_domain_ci_regression_repeats_ten_domain_chain(tmp_path: Path) -> None:
    result = build_cross_domain_ci_regression(tmp_path, rounds=3, min_domains=10, run_id="unit-cross-domain-ci")

    assert result["status"] == "ready"
    assert result["summary"]["round_count"] == 3
    assert result["summary"]["ready_round_count"] == 3
    assert result["summary"]["minimum_linked_domain_count"] >= 10
    assert result["summary"]["total_domain_replay_count"] >= 30
    assert result["summary"]["stable_domain_count"] is True
    assert result["summary"]["all_output_assertions_passed"] is True
    assert validate_contract("cross_domain_ci_regression_result", result)["valid"] is True


def test_service_exposes_cross_domain_ci_regression(tmp_path: Path) -> None:
    result = RetortService().cross_domain_ci_regression({"project": str(tmp_path), "rounds": 3, "min_domains": 10})

    assert result["status"] == "ready"
    assert result["summary"]["all_integrated_reviews_executed"] is True


def test_cross_domain_ci_regression_cli_outputs_contract(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "retort_engine.cli",
            "cross-domain-ci-regression",
            "--project",
            str(tmp_path),
            "--rounds",
            "3",
            "--min-domains",
            "10",
            "--json",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert validate_contract("cross_domain_ci_regression_result", payload)["valid"] is True
    assert payload["summary"]["ready_round_count"] == 3
