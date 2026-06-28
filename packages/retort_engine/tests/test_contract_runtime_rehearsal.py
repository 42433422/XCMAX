from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from retort_engine.contract_runtime_rehearsal import build_contract_runtime_rehearsal
from retort_engine.contracts import validate_contract
from retort_engine.service import RetortService


def test_contract_runtime_rehearsal_rejects_violations_and_rolls_back(tmp_path: Path) -> None:
    result = build_contract_runtime_rehearsal(tmp_path, run_id="unit-contract-runtime")

    assert result["status"] == "ready"
    assert result["summary"]["case_count"] == 3
    assert result["summary"]["violation_rejected_count"] == 3
    assert result["summary"]["rollback_verified_count"] == 3
    assert result["summary"]["valid_payload_accepted_count"] == 3
    assert result["summary"]["concurrent_worker_count"] == 6
    assert result["summary"]["concurrency_fault_injection_count"] == 18
    assert result["summary"]["concurrent_violation_rejected_count"] == 18
    assert result["summary"]["concurrent_rollback_verified_count"] == 18
    assert result["summary"]["all_violations_rejected"] is True
    assert result["summary"]["all_rollbacks_verified"] is True
    assert result["summary"]["all_concurrent_violations_rejected"] is True
    assert result["summary"]["all_concurrent_rollbacks_verified"] is True
    assert validate_contract("contract_runtime_rehearsal_result", result)["valid"] is True


def test_service_exposes_contract_runtime_rehearsal(tmp_path: Path) -> None:
    result = RetortService().contract_runtime_rehearsal({"project": str(tmp_path)})

    assert result["status"] == "ready"
    assert result["summary"]["all_valid_payloads_accepted"] is True


def test_contract_runtime_rehearsal_cli_outputs_contract(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "retort_engine.cli", "contract-runtime-rehearsal", "--project", str(tmp_path), "--json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert validate_contract("contract_runtime_rehearsal_result", payload)["valid"] is True
    assert payload["summary"]["all_rollbacks_verified"] is True
    assert payload["summary"]["all_concurrent_rollbacks_verified"] is True
