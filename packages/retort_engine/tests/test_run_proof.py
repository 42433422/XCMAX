from __future__ import annotations

import json
from pathlib import Path

from retort_engine.run_proof import build_absorption_run_proof, write_absorption_run_proof


def test_absorption_run_proof_binds_scores_core_graph_tests_and_llm(tmp_path: Path) -> None:
    graph_path = tmp_path / "docs" / "retort_code_graph_proof_run-1.json"
    graph_path.parent.mkdir(parents=True)
    graph_path.write_text(json.dumps({"run_id": "run-1", "node_count": 3, "edge_count": 2, "changed_file_count": 2}), encoding="utf-8")
    pre = {"project": str(tmp_path), "scores": [{"dimension": "calibrated_overall", "value": 70}], "metadata": {"score_source": "paibi_llm"}}
    external = {"project": "upstream", "scores": [{"dimension": "calibrated_overall", "value": 91}], "metadata": {"score_source": "paibi_llm"}}
    own = {
        "project": str(tmp_path),
        "scores": [{"dimension": "calibrated_overall", "value": 84}],
        "metadata": {
            "score_source": "paibi_llm",
            "llm_decision": "scored",
            "llm_task_id": "task-1",
            "capability_absorption_audit": {
                "behavior_source_files": ["retort_engine/core.py"],
                "behavior_test_files": ["tests/test_core.py"],
                "generated_evidence_files": ["docs/retort_external_review_report.json"],
                "latest_changed_source_line_count": 30,
                "latest_changed_test_line_count": 18,
                "latest_test_to_source_ratio": 0.6,
                "latest_test_to_source_ratio_status": "healthy",
                "reason": "latest_absorption_changed_behavior_code_and_tests",
                "risk_level": "low",
            },
        },
    }
    execution = {
        "run_id": "run-1",
        "status": "applied",
        "gates_passed": True,
        "changed_files": [str(tmp_path / "retort_engine" / "core.py"), str(tmp_path / "tests" / "test_core.py"), str(tmp_path / "docs" / "retort_external_review_report.json")],
        "gates": [{"ok": True}, {"ok": True}],
        "code_graph_proof_path": str(graph_path),
    }

    proof = build_absorption_run_proof(
        root=tmp_path,
        source="https://github.com/example/upstream",
        external_path=tmp_path / "external",
        pre_assessment=pre,
        external_assessment=external,
        own_assessment=own,
        tasks=[{"task_id": "task-a", "dimension": "architecture_depth"}],
        execution=execution,
        branch_state={"status": "merged"},
        absorption_state={"closed_loop_proof": {"verified": True, "flags": {"merge_verified": True}, "missing": []}},
        llm_review={"dispatch": {"task_id": "task-1", "status": "accepted"}},
    )
    path = write_absorption_run_proof(tmp_path, proof)
    stored = json.loads(path.read_text(encoding="utf-8"))

    assert stored["status"] == "bound_scored"
    assert stored["score_binding"]["score_delta"] == 14
    assert stored["score_binding"]["external_score"] == 91
    assert stored["core_change_binding"]["core_behavior_change_ratio"] == 0.667
    assert stored["code_graph_binding"]["node_count"] == 3
    assert stored["test_increment_binding"]["test_line_count"] == 18
    assert stored["llm_final_verdict"]["llm_task_id"] == "task-1"
    assert stored["closed_loop_binding"]["verified"] is True
