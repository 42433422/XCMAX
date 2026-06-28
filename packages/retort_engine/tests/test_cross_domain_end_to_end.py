from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.cross_domain_end_to_end import build_cross_domain_end_to_end
from retort_engine.service import RetortService


def test_cross_domain_end_to_end_links_all_direct_modules_into_one_review(tmp_path: Path) -> None:
    result = build_cross_domain_end_to_end(tmp_path, run_id="unit-cross-domain-e2e")

    assert result["status"] == "ready"
    assert result["summary"]["linked_stage_count"] == 10
    assert result["summary"]["linked_domain_count"] == 10
    assert result["summary"]["linked_direct_module_count"] == 10
    assert result["summary"]["integrated_review_status"] == "reviewed"
    assert result["summary"]["integrated_review_task_group_count"] > 0
    assert result["summary"]["all_stages_chained"] is True
    assert result["summary"]["all_stage_outputs_consumed"] is True
    assert result["summary"]["output_assertions_passed"] is True
    assert result["assertions"]["review_runtime_executed"] is True
    assert validate_contract("cross_domain_end_to_end_result", result)["valid"] is True


def test_service_exposes_cross_domain_end_to_end(tmp_path: Path) -> None:
    result = RetortService().cross_domain_end_to_end({"project": str(tmp_path), "min_domains": 10})

    assert result["status"] == "ready"
    assert result["summary"]["linked_domain_count"] == 10


def test_cross_domain_end_to_end_cli_outputs_contract(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "retort_engine.cli", "cross-domain-end-to-end", "--project", str(tmp_path), "--json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert validate_contract("cross_domain_end_to_end_result", payload)["valid"] is True
    assert payload["summary"]["all_stage_outputs_consumed"] is True
