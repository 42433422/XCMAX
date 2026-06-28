from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.cross_domain_absorption_replay import build_cross_domain_absorption_replay
from retort_engine.service import RetortService


def test_cross_domain_absorption_replay_executes_non_pr_core_modules(tmp_path: Path) -> None:
    result = build_cross_domain_absorption_replay(tmp_path, min_domains=10, run_id="unit-cross-domain")

    assert result["status"] == "ready"
    assert result["summary"]["ready_case_count"] == 10
    assert result["summary"]["non_pr_domain_count"] == 10
    assert result["summary"]["all_before_failed_after_passed"] is True
    assert result["summary"]["all_direct_modules_executed"] is True
    assert result["summary"]["all_output_assertions_passed"] is True
    assert "retort_engine.swe_bench_oracle.build_issue_patch_benchmark" in result["summary"]["direct_modules"]
    assert "retort_engine.architecture_contracts.evaluate_architecture_contracts" in result["summary"]["direct_modules"]
    assert "retort_engine.codebase_graph.build_codebase_graph" in result["summary"]["direct_modules"]
    assert "retort_engine.context_packager.build_context_pack" in result["summary"]["direct_modules"]
    assert "retort_engine.license_gate.license_gate" in result["summary"]["direct_modules"]
    assert "retort_engine.static_analysis_gate.scan_static_analysis_findings" in result["summary"]["direct_modules"]
    assert "retort_engine.intent_alignment.assess_change_intent_alignment" in result["summary"]["direct_modules"]
    assert "retort_engine.task_prioritization.build_task_prioritization_report" in result["summary"]["direct_modules"]
    assert "retort_engine.task_dispatch_plan.build_task_dispatch_plan" in result["summary"]["direct_modules"]
    assert "retort_engine.architecture_refactor.build_core_refactor_plan" in result["summary"]["direct_modules"]
    assert result["summary"]["independent_all_cases_accepted"] is True
    assert result["evidence"]["claim_boundary"] == "direct_core_modules_not_pr_review_manifest"
    assert validate_contract("cross_domain_absorption_replay_result", result)["valid"] is True


def test_cross_domain_absorption_replay_writes_report(tmp_path: Path) -> None:
    output = tmp_path / "docs" / "retort_cross_domain_absorption_replay.json"

    result = build_cross_domain_absorption_replay(tmp_path, output=output, run_id="write-cross-domain")

    assert result["status"] == "ready"
    assert output.is_file()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["summary"]["all_output_assertions_passed"] is True


def test_service_exposes_cross_domain_absorption_replay(tmp_path: Path) -> None:
    result = RetortService().cross_domain_absorption_replay({"project": str(tmp_path), "min_domains": 10})

    assert result["status"] == "ready"
    assert result["summary"]["non_pr_domain_count"] == 10


def test_cross_domain_absorption_replay_cli_outputs_contract(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "retort_engine.cli",
            "cross-domain-absorption-replay",
            "--project",
            str(tmp_path),
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
    assert validate_contract("cross_domain_absorption_replay_result", payload)["valid"] is True
    assert payload["summary"]["all_direct_modules_executed"] is True
