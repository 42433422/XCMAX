from scripts.dev.task_benchmark_report import summarize_planning_failures


def test_root_cause_does_not_depend_on_public_error_code():
    rows = [
        {
            "success": False,
            "error": "workflow_goal_coverage_rejected",
            "planning_failure_kind": "goal_coverage_rejected",
        }
        for _ in range(5)
    ] + [
        {
            "success": False,
            "error": "workflow_plan_rejected",
            "planning_failure_kind": "goal_coverage_rejected",
        }
        for _ in range(60)
    ]
    result = summarize_planning_failures(rows)
    assert result["root_causes"] == {"goal_coverage_rejected": 65}
    assert result["external_error_codes"]["workflow_goal_coverage_rejected"] == 5
    assert result["failures"] == 65


def test_legacy_failures_stay_unknown_and_do_not_mutate_records():
    rows = [{"success": False, "error": "workflow_plan_rejected"}, {"success": True}]
    report = summarize_planning_failures(rows)
    assert report["root_causes"] == {"unknown_legacy": 1}
    assert report["missing_root_cause"] == 1
    assert report["failures"] == 1
    assert "planning_failure_kind" not in rows[0]


def test_chat_and_plan_log_diagnostics_use_same_root_cause():
    report = summarize_planning_failures(
        [
            {"success": False, "data": {"planning_failure_kind": "plan_repair_failed"}},
            {"phase": "rejected", "planning_failure_kind": "plan_repair_failed"},
            {
                "metadata": {
                    "planning_rejected": True,
                    "planning_failure_kind": "plan_format_invalid",
                }
            },
            {},
        ]
    )
    assert report["root_causes"] == {"plan_format_invalid": 1, "plan_repair_failed": 2}
    assert report["unknown_outcomes"] == 1


def test_new_runtime_causes_and_missing_new_diagnostics_remain_distinct_from_legacy():
    report = summarize_planning_failures(
        [
            {"schema_version": 2, "success": False, "failure_kind": "rate_limited"},
            {"schema_version": 2, "success": False},
            {"success": False},
        ]
    )
    assert report["root_causes"] == {
        "diagnostic_missing": 1,
        "rate_limited": 1,
        "unknown_legacy": 1,
    }
