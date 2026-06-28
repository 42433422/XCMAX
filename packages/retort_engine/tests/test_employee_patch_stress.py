from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.employee_patch_stress import build_employee_patch_stress
from retort_engine.service import RetortService


def test_employee_patch_stress_rolls_back_more_than_100_failed_patches(tmp_path: Path) -> None:
    result = build_employee_patch_stress(tmp_path, concurrent_workers=101, run_id="unit-patch-stress")

    assert result["status"] == "ready"
    assert result["summary"]["worker_count"] == 101
    assert result["summary"]["concurrency_floor_exceeded"] is True
    assert result["summary"]["failed_gate_count"] == 101
    assert result["summary"]["rollback_verified_count"] == 101
    assert result["summary"]["post_rollback_gate_passed_count"] == 101
    assert result["summary"]["state_leak_count"] == 0
    assert result["summary"]["all_rollbacks_verified"] is True
    assert validate_contract("employee_patch_stress_result", result)["valid"] is True


def test_service_exposes_employee_patch_stress(tmp_path: Path) -> None:
    result = RetortService().employee_patch_stress({"project": str(tmp_path), "concurrent_workers": 101})

    assert result["status"] == "ready"
    assert result["summary"]["all_post_rollback_gates_passed"] is True


def test_employee_patch_stress_cli_outputs_contract(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "retort_engine.cli",
            "employee-patch-stress",
            "--project",
            str(tmp_path),
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
    assert validate_contract("employee_patch_stress_result", payload)["valid"] is True
    assert payload["summary"]["rollback_verified_count"] == 101
