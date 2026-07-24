from retort_engine.issue_capability_benchmark import (
    evaluate_issue_instances,
    synthesize_verified_issue_tasks,
)


def test_issue_evaluation_requires_patch_apply_and_fail_to_pass() -> None:
    result = evaluate_issue_instances(
        [{"instance_id": "good"}, {"instance_id": "false-positive"}],
        patch_producer=lambda item: f"patch:{item['instance_id']}",
        verifier=lambda item, _patch: {
            "patch_applied": True,
            "before_passed": item["instance_id"] == "false-positive",
            "after_passed": True,
        },
    )
    assert result["summary"]["resolved_count"] == 1
    assert result["summary"]["resolved_rate"] == 0.5
    assert result["instances"][1]["resolved"] is False


def test_task_synthesis_rejects_unverified_repairs() -> None:
    records = [
        {
            "test_id": "test_good",
            "failing_output": "failed",
            "patch": "diff",
            "before_passed": False,
            "after_passed": True,
        },
        {
            "test_id": "test_bad",
            "failing_output": "failed",
            "patch": "diff",
            "before_passed": False,
            "after_passed": False,
        },
    ]
    tasks = synthesize_verified_issue_tasks(records)
    assert [task["test_id"] for task in tasks] == ["test_good"]
    assert tasks[0]["oracle"] == "verified_fail_to_pass"
