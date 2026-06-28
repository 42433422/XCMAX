from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from retort_engine.contract_stability_stress import build_contract_stability_stress
from retort_engine.contracts import validate_contract
from retort_engine.service import RetortService


def test_contract_stability_stress_runs_more_than_100_workers_without_state_leak(tmp_path: Path) -> None:
    result = build_contract_stability_stress(tmp_path, rounds=2, concurrent_workers=101)

    assert result["status"] == "ready"
    assert result["summary"]["round_count"] == 2
    assert result["summary"]["concurrent_worker_count"] == 101
    assert result["summary"]["concurrency_floor_exceeded"] is True
    assert result["summary"]["total_fault_injection_count"] == 606
    assert result["summary"]["state_leak_count"] == 0
    assert result["summary"]["all_rounds_rejected_violations"] is True
    assert result["summary"]["all_rounds_verified_rollbacks"] is True
    assert validate_contract("contract_stability_stress_result", result)["valid"] is True


def test_service_exposes_contract_stability_stress(tmp_path: Path) -> None:
    result = RetortService().contract_stability_stress({"project": str(tmp_path), "rounds": 2, "concurrent_workers": 101})

    assert result["status"] == "ready"
    assert result["summary"]["state_leak_count"] == 0


def test_contract_stability_stress_cli_outputs_contract(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "retort_engine.cli",
            "contract-stability-stress",
            "--project",
            str(tmp_path),
            "--rounds",
            "2",
            "--concurrent-workers",
            "101",
            "--json",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert validate_contract("contract_stability_stress_result", payload)["valid"] is True
    assert payload["summary"]["concurrency_floor_exceeded"] is True
