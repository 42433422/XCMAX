from modstore_server.models_project_context import get_memos, record_execution_outcome


def test_self_maintenance_failed_steps_become_open_followups(tmp_path):
    employee_id = "vibe-coding-maintainer-followup-open"
    memory = {
        "open_items": [
            {
                "kind": "failed_steps",
                "run_id": "failed-review-run",
                "steps": ["review", "qa"],
            }
        ]
    }

    record_execution_outcome(
        employee_id=employee_id,
        task="Run MODstore self-maintenance follow-up",
        input_data={
            "workspace_root": str(tmp_path),
            "loop_kind": "scheduled_self_maintenance",
            "previous_loop_memory": memory,
        },
        outcome={"summary": "review follow-up still open"},
        status="failed",
    )

    employee_memory = get_memos(
        scope="employee",
        scope_key=employee_id,
        keys=["open_followups", "closed_followups", "next_self_maintenance_focus"],
    )

    assert {
        (item["source_run_id"], item["step"], item["status"])
        for item in employee_memory["open_followups"]
    } == {
        ("failed-review-run", "review", "open"),
        ("failed-review-run", "qa", "open"),
    }
    assert employee_memory["closed_followups"] == []
    assert employee_memory["next_self_maintenance_focus"]["status"] == "open"


def test_resolved_self_maintenance_followups_are_not_reopened(tmp_path):
    employee_id = "vibe-coding-maintainer-followup-close"
    memory = {
        "open_items": [
            {
                "kind": "failed_steps",
                "run_id": "failed-review-run",
                "steps": ["review"],
            }
        ]
    }

    record_execution_outcome(
        employee_id=employee_id,
        task="Run MODstore self-maintenance follow-up",
        input_data={
            "workspace_root": str(tmp_path),
            "loop_kind": "scheduled_self_maintenance",
            "previous_loop_memory": memory,
        },
        outcome={"summary": "review follow-up opened"},
        status="failed",
    )
    record_execution_outcome(
        employee_id=employee_id,
        task="Run MODstore self-maintenance follow-up",
        input_data={
            "workspace_root": str(tmp_path),
            "loop_kind": "scheduled_self_maintenance",
            "previous_loop_memory": memory,
            "resolved_run_ids": ["failed-review-run"],
        },
        outcome={"summary": "review follow-up passed"},
        status="success",
    )

    employee_memory = get_memos(
        scope="employee",
        scope_key=employee_id,
        keys=["open_followups", "closed_followups", "next_self_maintenance_focus"],
    )

    assert employee_memory["open_followups"] == []
    assert employee_memory["next_self_maintenance_focus"] == {"open_count": 0, "status": "clear"}
    assert any(
        item["source_run_id"] == "failed-review-run"
        and item["step"] == "review"
        and item["status"] == "closed"
        for item in employee_memory["closed_followups"]
    )
