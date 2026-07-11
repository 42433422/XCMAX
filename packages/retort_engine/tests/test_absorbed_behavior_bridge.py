from retort_engine.absorbed_behavior_bridge import absorbed_behavior_plan, verify_absorbed_behavior_imports


def test_absorbed_behavior_bridge_exposes_frontier_layers() -> None:
    plan = absorbed_behavior_plan()
    imports = verify_absorbed_behavior_imports()
    assert plan["run_id"]
    assert plan["source"]
    assert imports["run_bounded_agent_loop"] is True
    assert imports["persist_trajectory"] is True
    assert imports["run_command_with_process_group"] is True
    assert imports["compare_repository_gaps"] is True
    assert imports["run_heldout_oracle_suite"] is True
    assert set(imports["dimensions"]) == set(['bounded_execution', 'repository_intelligence', 'reproducible_evaluation', 'verified_task_synthesis'])
    assert len(imports["focus_targets"]) == 3
