from retort_engine.bounded_agent_loop import run_bounded_agent_loop


def test_bounded_agent_loop_separates_execution_and_goal_judgment() -> None:
    actions = iter(({"command": "inspect"}, {"command": "test"}))
    result = run_bounded_agent_loop(
        "finish repair",
        planner=lambda _objective, _trajectory: next(actions),
        executor=lambda action: {"output": action["command"], "returncode": 0},
        judge=lambda _objective, trajectory: {"complete": len(trajectory) == 2, "score": len(trajectory) * 50},
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
