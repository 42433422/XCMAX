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
    assert result["summary"]["per_run_code_graph_proved"] is True
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
        "proofPanel",
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
        "retort_employee_scheduler_stress.json": {"status": "ready", "summary": {}, "rounds": []},
        "retort_pr_publish_dry_run.json": {"status": "dry_run_ready", "summary": {}, "comments": []},
        "retort_pr_readonly_degradation_probe.json": {"status": "read_only_degraded", "summary": {}, "evidence": {}},
        "retort_pr_low_permission_probe.json": {"status": "permission_denied_degraded", "summary": {}, "evidence": {}},
        "retort_production_recovery_drill.json": {"status": "ready", "summary": {}, "scenarios": []},
        "retort_review_quality_benchmark.json": {"status": "ready", "summary": {"post_absorption_score_delta": 10}, "samples": []},
        "retort_external_advantage_matrix.json": {"status": "ready", "summary": {"score_delta": 50}, "matrix": []},
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
