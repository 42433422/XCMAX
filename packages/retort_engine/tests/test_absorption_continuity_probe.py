from __future__ import annotations

import json
from pathlib import Path

from retort_engine.absorption_continuity_probe import build_absorption_continuity_probe
from retort_engine.contracts import validate_contract
from retort_engine.service import RetortService


def test_absorption_continuity_probe_requires_repeated_proved_runs(tmp_path: Path) -> None:
    _write_run(tmp_path, "20260628010000-a", "github/a", code_graph=True)
    _write_employee_result(tmp_path, "20260628010000-a")
    _write_run(tmp_path, "20260628013000-b", "github/b", code_graph=True)
    _write_employee_result(tmp_path, "20260628013000-b")
    _write_closed_loop(tmp_path, "20260628013000-b")

    result = build_absorption_continuity_probe(tmp_path, min_runs=2)

    assert result["status"] == "ready"
    assert result["summary"]["ready_run_count"] == 2
    assert result["summary"]["distinct_source_count"] == 2
    assert result["summary"]["all_have_per_run_code_graph_proof"] is True
    assert result["summary"]["latest_closed_loop_verified"] is True
    assert result["summary"]["counting_model_separated"] is True
    assert validate_contract("absorption_continuity_probe_result", result)["valid"] is True


def test_absorption_continuity_probe_fails_missing_per_run_code_graph(tmp_path: Path) -> None:
    _write_run(tmp_path, "20260628010000-a", "github/a", code_graph=True)
    _write_employee_result(tmp_path, "20260628010000-a")
    _write_run(tmp_path, "20260628013000-b", "github/b", code_graph=False)
    _write_employee_result(tmp_path, "20260628013000-b")
    _write_closed_loop(tmp_path, "20260628013000-b")

    result = build_absorption_continuity_probe(tmp_path, min_runs=2)

    assert result["status"] == "needs_more_continuity"
    assert result["summary"]["all_have_per_run_code_graph_proof"] is False
    assert result["runs"][0]["code_graph_proof_missing"] == ["missing_per_run_code_graph_proof"]


def test_absorption_continuity_probe_accepts_post_absorption_hardening_run(tmp_path: Path) -> None:
    _write_run(tmp_path, "20260628013000-b", "github/b", code_graph=True)
    _write_employee_result(tmp_path, "20260628013000-b")
    _write_run(
        tmp_path,
        "20260628020000-hardening",
        "retort://post-absorption-hardening/abc1234",
        code_graph=True,
    )
    _write_employee_result(tmp_path, "20260628020000-hardening")
    _write_closed_loop(tmp_path, "20260628013000-b")

    result = build_absorption_continuity_probe(tmp_path, min_runs=2)

    assert result["status"] == "ready"
    assert result["latest_closed_loop"]["run_id"] == "20260628020000-hardening"
    assert result["latest_closed_loop"]["merge_commit"] == "abc1234"
    assert result["latest_closed_loop"]["required_flags"]["latest_run_referenced"] is True
    assert result["latest_closed_loop"]["required_flags"]["post_absorption_hardening_ready"] is True


def test_service_exposes_absorption_continuity_probe(tmp_path: Path) -> None:
    _write_run(tmp_path, "20260628010000-a", "github/a", code_graph=True)
    _write_employee_result(tmp_path, "20260628010000-a")
    _write_run(tmp_path, "20260628013000-b", "github/b", code_graph=True)
    _write_employee_result(tmp_path, "20260628013000-b")
    _write_closed_loop(tmp_path, "20260628013000-b")

    result = RetortService().absorption_continuity_probe({"project": str(tmp_path), "min_runs": 2})

    assert result["status"] == "ready"


def _write_run(root: Path, run_id: str, source: str, *, code_graph: bool) -> None:
    run_dir = root / ".retort" / "real_absorption_runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "source": source,
        "status": "applied",
        "gates_passed": True,
        "gates": [{"ok": True, "command": ["pytest"]}],
        "changed_files": [
            str(root / "retort_engine" / "review_context_bias.py"),
            str(root / "tests" / "test_review_context_bias.py"),
        ],
        "employee_results_path": str(root / ".retort" / "employee_results" / f"{run_id}.json"),
    }
    if code_graph:
        payload["code_graph_proof"] = {
            "run_id": run_id,
            "passed": True,
            "per_run_required": True,
            "status": "ready",
            "summary": {"graph_status": "ready", "changed_file_count": 2},
            "evidence": {
                "style": "deterministic_post_absorption_code_graph",
                "scope": "per_real_absorption_run",
            },
        }
    (run_dir / f"{run_id}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_employee_result(root: Path, run_id: str) -> None:
    result_dir = root / ".retort" / "employee_results"
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / f"{run_id}.json").write_text(
        json.dumps({"results": [{"task_id": "task", "status": "completed"}]}, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_closed_loop(root: Path, run_id: str) -> None:
    state = {
        "status": "closed_loop_verified",
        "source": "github/b",
        "closed_loop_proof": {
            "branch_diff_verified": True,
            "employee_execution_verified": True,
            "post_absorption_tests_passed": True,
            "merge_verified": True,
            "external_advantage_reassessed": True,
            "evidence": [
                f"employee_results={root / '.retort' / 'employee_results' / f'{run_id}.json'}",
                "merge_commit=abc1234",
                "code_graph_proof_passed=True",
            ],
        },
    }
    state_path = root / ".retort" / "absorption_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
