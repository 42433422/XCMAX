from __future__ import annotations

import json
from pathlib import Path

from retort_engine.absorption_state import advance_absorption_state, closed_loop_proof, load_absorption_state, public_absorption_state, record_absorption_shock, save_absorption_state


def test_record_absorption_shock_persists_public_state(tmp_path: Path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    tasks = [
        {"task_id": "one", "dimension": "architecture", "title": "A", "owner_hint": "core", "priority": "P1"},
        {"task_id": "two", "dimension": "tests", "title": "B", "owner_hint": "qa", "priority": "P1"},
    ]

    public = record_absorption_shock(tmp_path, "https://github.com/owner/repo", external, tasks)

    assert public["active"] is True
    assert public["status"] == "pending_llm_reassessment"
    assert public["external_path"] == str(external)
    assert public["pending_dimensions"] == ["architecture", "tests"]
    assert public["closed_loop_proof"]["verified"] is False
    assert load_absorption_state(tmp_path)["tasks"] == tasks


def test_advance_absorption_state_logs_self_evolution_actions(tmp_path: Path) -> None:
    record_absorption_shock(tmp_path, "repo", None, [{"task_id": "one", "dimension": "tests"}])

    finished = advance_absorption_state(tmp_path, ["architecture"], 3, [{"task_id": "fix", "dimension": "architecture"}])

    assert finished is False
    public = public_absorption_state(tmp_path)
    assert public["status"] == "awaiting_execution_evidence"
    assert public["resolved_round"] == 3
    assert public["resolved_dimensions"] == ["architecture", "tests"]
    log = tmp_path / ".retort" / "self_evolution_actions.jsonl"
    payload = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert payload["round_index"] == 3
    assert payload["resolved_dimensions"] == ["architecture", "tests"]


def test_closed_loop_proof_requires_all_five_flags(tmp_path: Path) -> None:
    save_absorption_state(
        tmp_path,
        {
            "closed_loop_proof": {
                "branch_diff_verified": True,
                "employee_execution_verified": True,
                "post_absorption_tests_passed": True,
                "merge_verified": True,
                "external_advantage_reassessed": True,
                "evidence": ["merge_cross_check=True", "pytest_gate_cross_check=True"],
            }
        },
    )

    proof = closed_loop_proof(tmp_path)

    assert proof["verified"] is True
    assert proof["missing"] == ()
    assert "merge_cross_check=True" in proof["evidence"]


def test_load_absorption_state_fails_closed_on_invalid_json(tmp_path: Path) -> None:
    state_path = tmp_path / ".retort" / "absorption_state.json"
    state_path.parent.mkdir()
    state_path.write_text("{invalid", encoding="utf-8")

    assert load_absorption_state(tmp_path) == {}
