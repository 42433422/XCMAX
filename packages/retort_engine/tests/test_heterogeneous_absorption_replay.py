from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.heterogeneous_absorption_replay import (
    HETEROGENEOUS_ABSORPTION_CASES,
    build_heterogeneous_absorption_replay,
)
from retort_engine.service import RetortService


def test_heterogeneous_absorption_replay_proves_before_failure_after_pass(tmp_path: Path) -> None:
    _seed_cached_sources(tmp_path)

    result = build_heterogeneous_absorption_replay(tmp_path)

    assert result["status"] == "ready"
    assert result["summary"]["case_count"] >= 6
    assert result["summary"]["ready_case_count"] == result["summary"]["case_count"]
    assert result["summary"]["cached_source_count"] == result["summary"]["case_count"]
    assert result["summary"]["language_family_count"] >= 4
    assert result["summary"]["source_family_count"] >= 4
    assert result["summary"]["pre_absorption_failure_count"] == result["summary"]["case_count"]
    assert result["summary"]["post_absorption_pass_count"] == result["summary"]["case_count"]
    assert result["summary"]["all_before_failed_after_passed"] is True
    assert result["summary"]["minimum_behavior_delta"] >= 35
    assert result["summary"]["independent_all_cases_accepted"] is True
    assert result["summary"]["cross_language_absorption_verified"] is True
    assert all(case["pre_absorption"]["failed_expected_behavior"] for case in result["cases"])
    assert all(case["post_absorption"]["passed_expected_behavior"] for case in result["cases"])
    assert validate_contract("heterogeneous_absorption_replay_result", result)["valid"] is True


def test_heterogeneous_absorption_replay_fails_without_cached_sources(tmp_path: Path) -> None:
    result = build_heterogeneous_absorption_replay(tmp_path)

    assert result["status"] == "needs_more_heterogeneous_evidence"
    assert result["summary"]["cached_source_count"] == 0
    assert result["summary"]["all_before_failed_after_passed"] is True
    assert result["summary"]["independent_all_cases_accepted"] is False


def test_heterogeneous_absorption_replay_writes_report(tmp_path: Path) -> None:
    _seed_cached_sources(tmp_path)
    output = tmp_path / "docs" / "retort_heterogeneous_absorption_replay.json"

    result = build_heterogeneous_absorption_replay(tmp_path, output=output)
    saved = json.loads(output.read_text(encoding="utf-8"))

    assert result["status"] == "ready"
    assert saved["summary"]["language_families"] == result["summary"]["language_families"]


def test_heterogeneous_absorption_replay_service_surface(tmp_path: Path) -> None:
    _seed_cached_sources(tmp_path)

    result = RetortService().heterogeneous_absorption_replay({"project": str(tmp_path)})

    assert result["status"] == "ready"
    assert result["summary"]["ready_case_count"] >= 6


def test_heterogeneous_absorption_replay_cli_outputs_contract(tmp_path: Path) -> None:
    _seed_cached_sources(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "retort_engine.cli",
            "heterogeneous-absorption-replay",
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
    assert validate_contract("heterogeneous_absorption_replay_result", payload)["valid"] is True


def _seed_cached_sources(root: Path) -> None:
    for case in HETEROGENEOUS_ABSORPTION_CASES:
        owner, repo = str(case["source_project"]).split("/", 1)
        (root / ".retort" / "cache" / "github" / owner / repo).mkdir(parents=True, exist_ok=True)
