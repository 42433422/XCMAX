from __future__ import annotations

import json
from pathlib import Path

from retort_engine.capability_audit import capability_absorption_audit, code_health, pr_review_runtime_evidence


def test_capability_audit_accepts_behavior_code_and_test_absorption(tmp_path: Path) -> None:
    source = tmp_path / "retort_engine" / "feature.py"
    test = tmp_path / "tests" / "test_feature.py"
    source.parent.mkdir()
    test.parent.mkdir()
    source.write_text("def feature():\n    return True\n", encoding="utf-8")
    test.write_text("def test_feature():\n    assert True\n", encoding="utf-8")
    run_dir = tmp_path / ".retort" / "real_absorption_runs"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps({"source": "https://github.com/example/repo", "changed_files": [str(source), str(test)]}),
        encoding="utf-8",
    )
    result_dir = tmp_path / ".retort" / "employee_results"
    result_dir.mkdir(parents=True)
    review_artifact = result_dir / "worker_review.json"
    review_artifact.write_text("{}", encoding="utf-8")
    (result_dir / "result.json").write_text(
        json.dumps({"execution_mode": "employee_runtime_worker", "runtime_evidence": {"worker_review": {"status": "reviewed", "comment_count": 1, "file_count": 1, "artifact": str(review_artifact)}}}),
        encoding="utf-8",
    )
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "retort_architecture_memory.json").write_text(json.dumps({"summary": {"source_count": 3}, "component_index": {}}), encoding="utf-8")

    audit = capability_absorption_audit(tmp_path)

    assert audit["reason"] == "latest_absorption_changed_behavior_code_and_tests"
    assert audit["behavior_source_files"] == ["retort_engine/feature.py"]
    assert audit["behavior_test_files"] == ["tests/test_feature.py"]
    assert audit["external_project_count"] == 3
    assert "employee_execution_not_independent_runtime" not in audit["blockers"]


def test_test_code_health_ignores_generated_absorption_files(tmp_path: Path) -> None:
    (tmp_path / "retort_engine").mkdir()
    (tmp_path / "retort_engine" / "core.py").write_text("def core():\n    return True\n", encoding="utf-8")
    (tmp_path / "retort_engine" / "absorbed_capabilities.py").write_text("generated = True\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_core.py").write_text("def test_core():\n    assert True\n", encoding="utf-8")

    health = code_health(tmp_path)

    assert health["source_file_count"] == 1
    assert health["test_file_count"] == 1


def test_pr_review_runtime_evidence_reports_missing_surface(tmp_path: Path) -> None:
    evidence = pr_review_runtime_evidence(tmp_path)

    assert evidence["runtime"] is False
    assert evidence["behavior_source_files"] == []
    assert evidence["behavior_test_files"] == []
