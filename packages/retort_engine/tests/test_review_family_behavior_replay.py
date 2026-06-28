from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.review_family_behavior_replay import build_review_family_behavior_replay
from retort_engine.service import RetortService


def test_review_family_behavior_replay_verifies_typescript_and_python_outputs(tmp_path: Path) -> None:
    result = build_review_family_behavior_replay(tmp_path, run_id="unit-review-family")

    assert result["status"] == "ready"
    assert result["summary"]["ready_case_count"] == 3
    assert result["summary"]["language_family_count"] == 2
    assert result["summary"]["typescript_case_count"] == 2
    assert result["summary"]["python_case_count"] == 1
    assert result["summary"]["all_direct_review_outputs_verified"] is True
    assert result["summary"]["publishable_case_count"] == 3
    assert result["summary"]["independent_all_cases_accepted"] is True
    assert validate_contract("review_family_behavior_replay_result", result)["valid"] is True


def test_service_exposes_review_family_behavior_replay(tmp_path: Path) -> None:
    result = RetortService().review_family_behavior_replay({"project": str(tmp_path)})

    assert result["status"] == "ready"
    assert result["summary"]["typescript_case_count"] == 2


def test_review_family_behavior_replay_cli_outputs_contract(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "retort_engine.cli", "review-family-behavior-replay", "--project", str(tmp_path), "--json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert validate_contract("review_family_behavior_replay_result", payload)["valid"] is True
    assert payload["summary"]["all_direct_review_outputs_verified"] is True
