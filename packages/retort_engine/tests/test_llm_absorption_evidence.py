from __future__ import annotations

import json
from pathlib import Path

from retort_engine.absorption_state import save_absorption_state
from retort_engine.llm_absorption_evidence import llm_absorption_evidence, read_json


def test_llm_absorption_evidence_collects_state_reports_and_audit_without_local_scores(tmp_path: Path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    save_absorption_state(
        tmp_path,
        {
            "source": "https://github.com/owner/repo",
            "external_path": str(external),
            "closed_loop_proof": {
                "branch_diff_verified": True,
                "employee_execution_verified": True,
                "post_absorption_tests_passed": True,
                "merge_verified": True,
                "external_advantage_reassessed": True,
                "evidence": ["merge_cross_check=True"],
            },
        },
    )
    source = tmp_path / "retort_engine" / "feature.py"
    test = tmp_path / "tests" / "test_absorbed_capabilities.py"
    source.parent.mkdir()
    test.parent.mkdir()
    source.write_text("def feature():\n    return True\n", encoding="utf-8")
    test.write_text("def test_feature():\n    assert True\n", encoding="utf-8")
    run_dir = tmp_path / ".retort" / "real_absorption_runs"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps({"source": "https://github.com/owner/repo", "changed_files": [str(source), str(test)]}),
        encoding="utf-8",
    )
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "retort_external_review_report.json").write_text(
        json.dumps(
            {
                "external_snapshot": {"git_revision": "abc123"},
                "absorbed_signals": ["pipeline", "benchmark"],
                "semantic_review": {"gaps": [{"name": "one"}]},
                "license_review": {"status": "passed", "detected_license": "MIT", "source_code_copy_allowed": True, "pattern_absorption_allowed": True, "isolation_policy": "license_gate_standard"},
                "review_pipeline": {
                    "component_gaps": [{"component": "core"}],
                    "prioritized_absorptions": [{"task": "split"}],
                    "benchmark": {"minimum_expected_behavior_tests": 2},
                },
            }
        ),
        encoding="utf-8",
    )
    result_dir = tmp_path / ".retort" / "employee_results"
    result_dir.mkdir(parents=True)
    (result_dir / "result.json").write_text(
        json.dumps(
            {
                "execution_mode": "employee_runtime_worker",
                "results": [{"task_id": "one"}],
                "runtime_evidence": {"worker_review": {"status": "reviewed", "comment_count": 2, "artifact": "review.json"}},
            }
        ),
        encoding="utf-8",
    )

    evidence = llm_absorption_evidence(tmp_path)

    assert "absorption_source=https://github.com/owner/repo" in evidence
    assert f"external_materialized_path={external}; exists=True" in evidence
    assert "closed_loop_five_proofs_verified=True" in evidence
    assert "capability_absorption_local_score_removed=True" in evidence
    assert not any(item.startswith("capability_absorption_score=") for item in evidence)
    assert not any(item.startswith("capability_absorption_cap=") for item in evidence)
    assert "behavior_test_function_count=1" in evidence
    assert "external_snapshot_revision=abc123" in evidence
    assert "semantic_gap_count=1" in evidence
    assert "license_review_status=passed; detected=MIT; source_copy_allowed=True; pattern_absorption_allowed=True; isolation=license_gate_standard" in evidence
    assert "component_gap_count=1" in evidence
    assert "employee_result_count=1; execution_mode=employee_runtime_worker" in evidence
    assert "employee_runtime_worker_review=reviewed; comments=2; artifact=review.json" in evidence
    assert "merge_cross_check=True" in evidence


def test_llm_absorption_evidence_read_json_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    assert read_json(path) == {}
