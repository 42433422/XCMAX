from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.external_advantage_repeat import build_external_advantage_repeat
from retort_engine.service import RetortService


def test_external_advantage_repeat_proves_stable_replay_manifest(tmp_path: Path) -> None:
    result = build_external_advantage_repeat(tmp_path, repeat_count=2)

    assert result["status"] == "ready"
    assert result["summary"]["ready_repeat_count"] == 2
    assert result["summary"]["total_case_evaluation_count"] >= 12
    assert result["summary"]["stable_case_set"] is True
    assert result["summary"]["stable_score_delta"] is True
    assert result["summary"]["minimum_score_delta"] >= 35
    assert validate_contract("external_advantage_repeat_result", result)["valid"] is True


def test_external_advantage_repeat_writes_report(tmp_path: Path) -> None:
    output = tmp_path / "docs" / "retort_external_advantage_repeat.json"

    result = build_external_advantage_repeat(tmp_path, output=output)
    saved = json.loads(output.read_text(encoding="utf-8"))

    assert result["status"] == "ready"
    assert saved["summary"]["score_deltas"] == result["summary"]["score_deltas"]


def test_external_advantage_repeat_service_surface(tmp_path: Path) -> None:
    result = RetortService().external_advantage_repeat({"project": str(tmp_path), "repeats": 2})

    assert result["status"] == "ready"
    assert result["summary"]["all_runs_ready"] is True


def test_external_advantage_repeat_cli_outputs_contract(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "retort_engine.cli",
            "external-advantage-repeat",
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
    assert validate_contract("external_advantage_repeat_result", payload)["valid"] is True
