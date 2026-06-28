from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from retort_engine.absorption_hardening_run import record_post_absorption_hardening_run
from retort_engine.contracts import validate_contract


def test_record_post_absorption_hardening_run_materializes_latest_behavior_diff(tmp_path: Path) -> None:
    _git(["init"], tmp_path)
    _git(["config", "user.email", "retort@example.test"], tmp_path)
    _git(["config", "user.name", "Retort Test"], tmp_path)
    (tmp_path / "retort_engine").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "retort_engine" / "pr_review.py").write_text("def review():\n    return 'base'\n", encoding="utf-8")
    (tmp_path / "tests" / "test_pr_review.py").write_text("def test_review():\n    assert True\n", encoding="utf-8")
    (tmp_path / "docs" / "retort_quality_gate_bundle.json").write_text(
        json.dumps({"status": "ready", "summary": {"all_gates_passed": True}}),
        encoding="utf-8",
    )
    _git(["add", "."], tmp_path)
    _git(["commit", "-m", "base absorption merge"], tmp_path)
    merge_commit = _git(["rev-parse", "HEAD"], tmp_path).stdout.strip()
    state = tmp_path / ".retort" / "absorption_state.json"
    state.parent.mkdir()
    state.write_text(json.dumps({"closed_loop_proof": {"evidence": [f"merge_commit={merge_commit}"]}}), encoding="utf-8")
    _git(["add", "."], tmp_path)
    _git(["commit", "-m", "record merge state"], tmp_path)
    (tmp_path / "retort_engine" / "external_advantage_matrix.py").write_text("def matrix():\n    return {'ready': True}\n", encoding="utf-8")
    (tmp_path / "tests" / "test_external_advantage_matrix.py").write_text("def test_matrix():\n    assert True\n", encoding="utf-8")
    (tmp_path / "docs" / "retort_external_advantage_matrix.json").write_text(json.dumps({"status": "ready"}), encoding="utf-8")
    _git(["add", "."], tmp_path)
    _git(["commit", "-m", "harden absorption behavior"], tmp_path)

    result = record_post_absorption_hardening_run(tmp_path, python_executable=sys.executable)

    assert result["status"] == "applied"
    assert result["gates_passed"] is True
    assert result["summary"]["behavior_source_file_count"] >= 1
    assert result["summary"]["behavior_test_file_count"] >= 1
    assert result["code_graph_proof"]["run_id"] == result["run_id"]
    assert Path(result["employee_results_path"]).is_file()
    assert Path(result["run_record_path"]).is_file()
    assert validate_contract("hardening_run_result", result)["valid"] is True


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
