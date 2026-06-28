from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.external_process_adjudication import build_external_process_adjudication
from retort_engine.service import RetortService


def test_external_process_adjudication_runs_outside_retort_package(tmp_path: Path) -> None:
    result = build_external_process_adjudication(tmp_path, run_id="unit-external-process")

    assert result["status"] == "ready"
    assert result["summary"]["external_accepted_case_count"] == 6
    assert result["summary"]["external_minimum_delta"] >= 80
    assert result["summary"]["script_imports_retort_engine"] is False
    assert result["summary"]["score_fields_consumed"] is False
    assert result["summary"]["input_sha256"]
    assert result["summary"]["output_sha256"]
    assert validate_contract("external_process_adjudication_result", result)["valid"] is True


def test_service_exposes_external_process_adjudication(tmp_path: Path) -> None:
    result = RetortService().external_process_adjudication({"project": str(tmp_path)})

    assert result["status"] == "ready"
    assert result["summary"]["external_all_cases_accepted"] is True


def test_external_process_adjudication_cli_outputs_contract(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "retort_engine.cli", "external-process-adjudication", "--project", str(tmp_path), "--json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert validate_contract("external_process_adjudication_result", payload)["valid"] is True
    assert payload["summary"]["external_delta_floor_met"] is True
