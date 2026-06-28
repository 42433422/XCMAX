from __future__ import annotations

import json
import subprocess
from pathlib import Path

from retort_engine.capability_audit import absorption_external_projects, capability_absorption_audit, code_health, post_absorption_hardening_files, pr_review_runtime_evidence


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
    assert "https://github.com/example/repo" in audit["external_projects"]
    assert len(audit["external_projects"]) == 3
    assert "employee_execution_not_independent_runtime" not in audit["blockers"]


def test_absorption_external_projects_combines_run_sources_and_architecture_memory(tmp_path: Path) -> None:
    run_dir = tmp_path / ".retort" / "real_absorption_runs"
    run_dir.mkdir(parents=True)
    (run_dir / "one.json").write_text(json.dumps({"source": "https://github.com/a/one"}), encoding="utf-8")
    (run_dir / "duplicate.json").write_text(json.dumps({"source": "https://github.com/a/one"}), encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "retort_architecture_memory.json").write_text(
        json.dumps(
            {
                "summary": {"source_count": 3},
                "component_index": {
                    "ui": {"sources": ["https://github.com/b/two"]},
                },
            }
        ),
        encoding="utf-8",
    )

    projects = absorption_external_projects(tmp_path)

    assert "https://github.com/a/one" in projects
    assert "https://github.com/b/two" in projects
    assert len(projects) == 3


def test_capability_audit_counts_post_absorption_core_hardening(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, stdout=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "retort@example.test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Retort Test"], cwd=tmp_path, check=True)
    run_dir = tmp_path / ".retort" / "real_absorption_runs"
    run_dir.mkdir(parents=True)
    generated = tmp_path / "retort_engine" / "absorbed_capabilities.py"
    generated.parent.mkdir()
    generated.write_text("GENERATED = True\n", encoding="utf-8")
    (run_dir / "run.json").write_text(json.dumps({"source": "https://github.com/example/repo", "changed_files": [str(generated)]}), encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "merge absorption"], cwd=tmp_path, check=True, stdout=subprocess.PIPE)
    merge_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, text=True, stdout=subprocess.PIPE).stdout.strip()
    state = tmp_path / ".retort" / "absorption_state.json"
    state.write_text(json.dumps({"closed_loop_proof": {"evidence": [f"merge_commit={merge_commit}"]}}), encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "record absorption state"], cwd=tmp_path, check=True, stdout=subprocess.PIPE)
    for rel in ("retort_engine/pr_review.py", "retort_engine/review_quality_benchmark.py", "retort_engine/llm_absorption_evidence.py", "tests/test_pr_review.py"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def testable():\n    return True\n" if rel.startswith("retort_engine/") else "def test_testable():\n    assert True\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "harden after absorption"], cwd=tmp_path, check=True, stdout=subprocess.PIPE)

    hardening = post_absorption_hardening_files(tmp_path)
    audit = capability_absorption_audit(tmp_path)

    assert len(hardening["behavior_source_files"]) == 3
    assert hardening["behavior_test_files"] == ["tests/test_pr_review.py"]
    assert "retort_engine/pr_review.py" in audit["post_absorption_hardening"]["behavior_source_files"]
    assert "latest_absorption_missing_core_behavior_diff" not in audit["blockers"]


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


def test_pr_review_runtime_evidence_reports_extension_policy_depth() -> None:
    project = Path(__file__).resolve().parents[1]

    evidence = pr_review_runtime_evidence(project)

    assert evidence["extension_policy_known_count"] >= 8
    assert evidence["extension_policy_unknown_count"] == 0
    assert evidence["extension_policy_language_family_count"] >= 7
    assert evidence["extension_policy_review_context_count"] >= 4
    assert {"runtime", "frontend", "ci_config", "docs", "config"}.issubset(set(evidence["extension_policy_review_contexts"]))
    assert "retort_engine/diff_extension_policy.py" in evidence["behavior_source_files"]
    assert "tests/test_diff_extension_policy.py" in evidence["behavior_test_files"]
