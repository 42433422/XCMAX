from pathlib import Path
from typing import Any

from retort_engine.bounded_agent_loop import (
    detect_stuck_pattern,
    load_trajectory,
    run_bounded_agent_loop,
)
from retort_engine.issue_capability_benchmark import run_heldout_oracle_suite
from retort_engine.process_safety import probe_timeout_kills_child
from retort_engine.repository_intelligence import compare_repository_gaps


def test_bounded_agent_loop_separates_execution_and_goal_judgment() -> None:
    actions = iter(({"command": "inspect"}, {"command": "test"}))
    result = run_bounded_agent_loop(
        "finish repair",
        planner=lambda _objective, _trajectory: next(actions),
        executor=lambda action: {"output": action["command"], "returncode": 0},
        judge=lambda _objective, trajectory: {
            "complete": len(trajectory) == 2,
            "score": len(trajectory) * 50,
        },
        max_steps=3,
        wall_time_limit_sec=2,
    )
    assert result["status"] == "complete"
    assert result["summary"]["step_count"] == 2
    assert result["summary"]["final_score"] == 100
    assert result["trajectory"][0]["action"]["command"] == "inspect"


def test_bounded_agent_loop_stops_repeating_action_observation_cycle() -> None:
    result = run_bounded_agent_loop(
        "avoid loop",
        planner=lambda _objective, _trajectory: {"command": "same"},
        executor=lambda _action: {"output": "same error", "returncode": 1},
        judge=lambda _objective, _trajectory: {"complete": False, "score": 0},
        max_steps=10,
        wall_time_limit_sec=2,
        repeat_limit=3,
    )
    assert result["status"] == "stuck"
    assert result["summary"]["step_count"] == 3


def test_bounded_agent_loop_persists_trajectory(tmp_path: Path) -> None:
    actions = iter(({"command": "a"}, {"command": "b"}))
    result = run_bounded_agent_loop(
        "persist",
        planner=lambda _objective, _trajectory: next(actions),
        executor=lambda action: {"ok": True, "command": action["command"]},
        judge=lambda _objective, trajectory: {
            "complete": len(trajectory) >= 2,
            "score": 100,
        },
        max_steps=3,
        wall_time_limit_sec=2,
        trajectory_dir=tmp_path,
        run_id="persist-test",
    )
    path = Path(result["summary"]["trajectory_path"])
    assert path.is_file()
    loaded = load_trajectory(path)
    assert loaded["status"] == "complete"
    assert len(loaded["trajectory"]) == 2


def test_detect_alternating_stuck_pattern() -> None:
    trajectory = [
        {"action": {"command": "a"}, "observation": {"ok": True}},
        {"action": {"command": "b"}, "observation": {"ok": True}},
        {"action": {"command": "a"}, "observation": {"ok": True}},
        {"action": {"command": "b"}, "observation": {"ok": True}},
    ]
    assert detect_stuck_pattern(trajectory, repeat_limit=2) == "alternating_cycle"


def test_bounded_agent_loop_accepts_process_safe_command_runner() -> None:
    calls: list[list[str]] = []

    def runner(command: list[str]) -> dict[str, Any]:
        calls.append(command)
        return {"returncode": 0, "stdout_tail": "ok", "process_group_killed": False}

    result = run_bounded_agent_loop(
        "use safe runner",
        planner=lambda _objective, _trajectory: {"command": ["echo", "hi"]},
        executor=lambda _action: {"should_not": "run"},
        judge=lambda _objective, _trajectory: {"complete": True, "score": 100},
        max_steps=2,
        wall_time_limit_sec=2,
        command_runner=runner,
    )
    assert result["status"] == "complete"
    assert result["summary"]["command_runner_injected"] is True
    assert calls == [["echo", "hi"]]
    assert result["trajectory"][0]["observation"]["returncode"] == 0


def test_process_safety_timeout_kills_group() -> None:
    probe = probe_timeout_kills_child(timeout_sec=0.4)
    assert probe["verified"] is True


def test_heldout_oracle_suite_resolves_real_pytest_cases() -> None:
    root = Path(__file__).resolve().parents[1]
    result = run_heldout_oracle_suite(root)
    assert result["summary"]["all_resolved"] is True
    assert result["summary"]["verified_task_count"] >= 2


def test_compare_repository_gaps_emits_targets(tmp_path: Path) -> None:
    own = tmp_path / "own"
    external = tmp_path / "external"
    (own / "pkg").mkdir(parents=True)
    (external / "pkg").mkdir(parents=True)
    (own / "pkg" / "core.py").write_text(
        "def absorb():\n    return 1\n", encoding="utf-8"
    )
    (own / "pkg" / "helper.py").write_text(
        "from pkg.core import absorb\n", encoding="utf-8"
    )
    (external / "pkg" / "core.py").write_text(
        "def absorb():\n    return 1\n\ndef rank_files():\n    return []\n",
        encoding="utf-8",
    )
    (external / "pkg" / "helper.py").write_text(
        "from pkg.core import absorb, rank_files\n", encoding="utf-8"
    )
    gap = compare_repository_gaps(own, external, focus_terms=("absorb",), max_files=8)
    assert gap["summary"]["decision_source"] == "repository_graph_gap"
    assert gap["own_top_targets"]
