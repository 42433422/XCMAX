from __future__ import annotations

import json
from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.operator_journey_replay import build_operator_journey_replay
from retort_engine.service import RetortService


def test_operator_journey_replay_builds_hash_bound_end_to_end_pack(tmp_path: Path) -> None:
    _write_project_fixture(tmp_path)

    result = build_operator_journey_replay(tmp_path, output=tmp_path / "docs" / "retort_operator_journey_replay.json")

    assert result["status"] == "ready"
    assert result["summary"]["ready_stage_count"] == result["summary"]["stage_count"]
    assert result["summary"]["hashed_artifact_count"] >= 8
    assert result["summary"]["cross_domain_live_probe_ready"] is True
    assert result["summary"]["frontend_operation_replay_ready"] is True
    assert result["summary"]["per_run_code_graph_proved"] is True
    assert result["summary"]["external_advantage_ci_ready"] is True
    assert result["summary"]["external_process_adjudication_ready"] is True
    assert result["summary"]["upstream_pr_ci_ready"] is True
    assert result["summary"]["competitor_runtime_ready"] is True
    assert result["summary"]["employee_patch_stress_ready"] is True
    assert result["summary"]["contract_stability_ready"] is True
    assert result["summary"]["cross_domain_end_to_end_ready"] is True
    assert result["summary"]["cross_domain_ci_regression_ready"] is True
    assert Path(result["summary"]["manifest_path"]).is_file()
    assert all(item["sha256"] for item in result["artifacts"] if item["exists"])
    assert validate_contract("operator_journey_replay_result", result)["valid"] is True


def test_operator_journey_replay_blocks_without_latest_absorption_run(tmp_path: Path) -> None:
    _write_project_fixture(tmp_path)
    for path in (tmp_path / ".retort" / "real_absorption_runs").glob("*.json"):
        path.unlink()

    result = build_operator_journey_replay(tmp_path)

    assert result["status"] == "blocked"
    assert result["summary"]["real_absorption_run_present"] is False
    assert any(stage["name"] == "select_external_source" and not stage["ready"] for stage in result["stages"])


def test_operator_journey_replay_accepts_post_absorption_graph_focus(tmp_path: Path) -> None:
    _write_project_fixture(tmp_path)
    run_path = tmp_path / ".retort" / "real_absorption_runs" / "fixture-run.json"
    payload = json.loads(run_path.read_text(encoding="utf-8"))
    payload.pop("pre_absorption_focus")
    payload["source"] = "retort://post-absorption-hardening/abc1234"
    payload["code_graph_proof"]["changed_focus_files"] = ["retort_engine/codebase_graph.py"]
    run_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = build_operator_journey_replay(tmp_path)

    stage = next(item for item in result["stages"] if item["name"] == "pre_absorption_locate")
    assert result["status"] == "ready"
    assert stage["ready"] is True
    assert "location_evidence=post_absorption_code_graph_focus" in stage["evidence"]


def test_service_exposes_operator_journey_replay(tmp_path: Path) -> None:
    _write_project_fixture(tmp_path)

    result = RetortService().operator_journey_replay({"project": str(tmp_path)})

    assert result["status"] == "ready"


def _write_project_fixture(root: Path) -> None:
    _write_source_tree(root)
    _write_frontend(root)
    _write_docs(root)
    _write_latest_absorption_run(root)


def _write_source_tree(root: Path) -> None:
    package = root / "retort_engine"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "codebase_graph.py").write_text(
        "def build():\n    return {'status': 'ready'}\n",
        encoding="utf-8",
    )
    (package / "contracts.py").write_text(
        "SCHEMAS = {'operator_journey_replay_result': ('status',)}\n",
        encoding="utf-8",
    )


def _write_frontend(root: Path) -> None:
    frontend = root / "retort_engine" / "frontend"
    frontend.mkdir(parents=True, exist_ok=True)
    ids = [
        "blackholeCanvas",
        "deepProgress",
        "progressFill",
        "progressSteps",
        "eventList",
        "sessionState",
        "sourceGithub",
        "githubUrl",
        "assessBtn",
        "absorbBtn",
        "executionState",
        "dualReviewPanel",
        "comparisonPanel",
        "proofPanel",
        "finalReviewPanel",
        "codeGraphProofPanel",
        "refactorPriorityPanel",
        "codeGraphFocusPanel",
    ]
    body = "\n".join(f'<div id="{item}"></div>' for item in ids if item != "blackholeCanvas")
    (frontend / "index.html").write_text(
        f'<canvas id="blackholeCanvas" data-visual="blackhole-accretion-field"></canvas>{body}<script src="/app.js"></script>',
        encoding="utf-8",
    )
    (frontend / "app.js").write_text(
        "\n".join(
            [
                'const canvas = document.getElementById("blackholeCanvas");',
                'canvas.getContext("2d");',
                "function drawAbsorptionScene() {}",
                "function drawAbsorptionPlanet() {}",
                "function renderDevourSession() {}",
                "function beginAbsorption() {}",
                "function setMode(mode) {}",
                "function assess() {}",
                "function absorb() {}",
                "function refreshEvolutionMap() {}",
                "function handleAbsorbedProjectClick() { selectAbsorbedProject(); }",
                "function selectAbsorbedProject() {}",
                "$('assessBtn').onclick = assess;",
                "$('absorbBtn').onclick = absorb;",
                "setMode(\"github\");",
                "codeGraphProofPanel; refactorPriorityPanel;",
                "canvas.addEventListener(\"click\", handleAbsorbedProjectClick);",
                "function draw() { requestAnimationFrame(draw); }",
            ]
        ),
        encoding="utf-8",
    )


def _write_docs(root: Path) -> None:
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    fixtures = {
        "retort_external_review_report.json": {"source": "github", "external_snapshot": {}, "review_pipeline": {}},
        "retort_quality_gate_bundle.json": {"status": "ready", "summary": {"all_gates_passed": True}, "gates": []},
        "retort_absorption_continuity_probe.json": {"status": "ready", "summary": {}, "runs": []},
        "retort_multi_project_absorption_replay.json": {"status": "ready", "summary": {}, "projects": []},
        "retort_pr_long_run_review.json": {"status": "ready", "summary": {}, "pull_requests": [], "evidence": {}},
        "retort_pr_holdout_blind_eval.json": {"status": "ready", "summary": {}, "cases": []},
        "retort_pr_failure_rollback_replay.json": {"status": "ready", "summary": {}, "cases": []},
        "retort_employee_patch_closure.json": {"status": "ready", "summary": {}, "cases": []},
        "retort_employee_patch_stress.json": {
            "status": "ready",
            "summary": {
                "concurrency_floor_exceeded": True,
                "worker_count": 120,
                "rollback_verified_count": 120,
                "all_post_rollback_gates_passed": True,
            },
            "workers": [],
        },
        "retort_employee_scheduler_stress.json": {"status": "ready", "summary": {"unique_successful_process_id_count": 30}, "rounds": []},
        "retort_pr_publish_dry_run.json": {"status": "dry_run_ready", "summary": {}, "comments": []},
        "retort_pr_readonly_degradation_probe.json": {"status": "read_only_degraded", "summary": {}, "evidence": {}},
        "retort_pr_low_permission_probe.json": {"status": "permission_denied_degraded", "summary": {}, "evidence": {}},
        "retort_production_recovery_drill.json": {"status": "ready", "summary": {}, "scenarios": []},
        "retort_review_quality_benchmark.json": {"status": "ready", "summary": {"post_absorption_score_delta": 10}, "samples": []},
        "retort_external_advantage_matrix.json": {
            "status": "ready",
            "summary": {"score_delta": 50, "blind_third_party_all_cases_accepted": True, "blind_third_party_minimum_delta": 65},
            "matrix": [],
        },
        "retort_external_advantage_ci_regression.json": {
            "status": "ready",
            "summary": {
                "all_cases_have_ci_acceptance": True,
                "all_direct_review_regressions_verified": True,
                "blind_third_party_minimum_delta": 80,
            },
            "cases": [],
        },
        "retort_external_process_adjudication.json": {
            "status": "ready",
            "summary": {"external_all_cases_accepted": True, "script_imports_retort_engine": False},
            "cases": [],
        },
        "retort_external_advantage_repeat.json": {"status": "ready", "summary": {"stable_case_set": True, "stable_score_delta": True}, "runs": []},
        "retort_upstream_pr_ci_probe.json": {
            "status": "ready",
            "summary": {"merged": True, "all_check_runs_successful": True},
            "check_runs": [],
        },
        "retort_competitor_runtime_comparison.json": {
            "status": "ready",
            "summary": {
                "side_by_side_output_materialized": True,
                "multi_competitor_side_by_side": True,
                "ready_competitor_project_count": 3,
                "all_live_upstream_sources_verified": True,
            },
            "competitor_output": {},
        },
        "retort_heterogeneous_absorption_replay.json": {
            "status": "ready",
            "summary": {"all_before_failed_after_passed": True, "cross_language_absorption_verified": True},
            "cases": [],
        },
        "retort_cross_domain_absorption_replay.json": {
            "status": "ready",
            "summary": {
                "all_before_failed_after_passed": True,
                "all_output_assertions_passed": True,
                "non_pr_domain_count": 10,
            },
            "cases": [],
        },
        "retort_cross_domain_end_to_end.json": {
            "status": "ready",
            "summary": {"all_stages_chained": True, "all_stage_outputs_consumed": True},
            "stages": [],
        },
        "retort_cross_domain_ci_regression.json": {
            "status": "ready",
            "summary": {
                "ready_round_count": 3,
                "round_count": 3,
                "all_output_assertions_passed": True,
            },
            "runs": [],
        },
        "retort_contract_runtime_rehearsal.json": {
            "status": "ready",
            "summary": {
                "all_violations_rejected": True,
                "all_rollbacks_verified": True,
                "all_concurrent_violations_rejected": True,
                "all_concurrent_rollbacks_verified": True,
            },
            "cases": [],
        },
        "retort_contract_stability_stress.json": {
            "status": "ready",
            "summary": {"concurrency_floor_exceeded": True, "state_leak_count": 0},
            "runs": [],
        },
        "retort_review_family_behavior_replay.json": {
            "status": "ready",
            "summary": {"all_direct_review_outputs_verified": True, "independent_all_cases_accepted": True},
            "cases": [],
        },
        "retort_external_merge_landing.json": {
            "status": "ready",
            "summary": {"all_branch_diff_merge_tests_passed": True, "merge_commit_count": 10, "post_merge_test_passed_count": 10},
            "cases": [],
        },
        "retort_review_adjudication_calibration.json": {"status": "ready", "summary": {}, "cases": []},
        "retort_absorption_release_decision.json": {"status": "ready", "summary": {"all_core_decisions_ready": True}, "decisions": []},
    }
    for name, payload in fixtures.items():
        (docs / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_latest_absorption_run(root: Path) -> None:
    run_dir = root / ".retort" / "real_absorption_runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": "fixture-run",
        "status": "applied",
        "source": "github.com/example/project",
        "summary": {},
        "gates_passed": True,
        "changed_files": ["retort_engine/codebase_graph.py", "tests/test_operator_journey_replay.py"],
        "employee_results_path": str(root / ".retort" / "employee_results" / "fixture.json"),
        "pre_absorption_focus": {"own_focus_files": ["retort_engine/codebase_graph.py"]},
        "code_graph_proof": {"passed": True, "per_run_required": True, "status": "proved"},
    }
    (run_dir / "fixture-run.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
