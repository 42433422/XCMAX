import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.release_gate

from modstore_server.autonomy_scheduler import (  # noqa: E402
    _reconcile_completed_loop_memory_safely,
    pending_automated_remediation,
    register_autonomy_jobs,
    run_pending_automated_remediation,
    self_maintenance_cooldown_minutes,
)


@pytest.fixture(autouse=True)
def _disable_real_memory_reconciliation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "modstore_server.autonomy_scheduler._reconcile_completed_loop_memory_safely",
        lambda: None,
    )


def test_memory_reconciliation_failure_does_not_block_scheduler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail() -> None:
        raise OSError("ledger unavailable")

    monkeypatch.setattr(
        "modstore_server.self_maintenance_memory_reconciliation."
        "reconcile_completed_loop_memory_from_ledger",
        _fail,
    )

    _reconcile_completed_loop_memory_safely()


def test_remediation_trigger_uses_shorter_bounded_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_COOLDOWN_MINUTES", "360")
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_INCIDENT_COOLDOWN_MINUTES", "45")
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_REMEDIATION_COOLDOWN_MINUTES", "5")

    assert self_maintenance_cooldown_minutes("scheduler") == 360
    assert self_maintenance_cooldown_minutes("incident_event") == 45
    assert self_maintenance_cooldown_minutes("automated_remediation") == 15


def test_pending_remediation_requires_executable_branch_and_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = {
        "open_items": [
            {
                "kind": "automated_remediation",
                "reason": "structured_review_blocking_findings",
                "run_id": "run-42",
                "branch": "devfleet/trae/fix-42",
                "task_id": "task-42",
            }
        ]
    }
    monkeypatch.setattr(
        "modstore_server.self_maintenance_loop_runner._load_loop_memory",
        lambda: memory,
    )

    assert pending_automated_remediation() == {
        "branch": "devfleet/trae/fix-42",
        "reason": "structured_review_blocking_findings",
        "run_id": "run-42",
        "task_id": "task-42",
    }

    memory["open_items"][0]["task_id"] = ""
    assert pending_automated_remediation() is None


def test_pending_remediation_normalizes_legacy_target_ref_verdict_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    branch = "devfleet/cursor/sub-1-legacy-target-ref"
    memory = {
        "last_policy_decision": {
            "reason": "structured_qa_verdict_not_pass",
            "structured_gate": {
                "qa": {
                    "blocking_findings": [
                        f"target_branch_unavailable: refs/remotes/origin/{branch} cannot be resolved"
                    ],
                    "target_branch_available": False,
                    "verdict": "FAIL",
                },
                "reason": "structured_qa_verdict_not_pass",
            },
        },
        "open_items": [
            {
                "kind": "automated_remediation",
                "reason": "structured_qa_verdict_not_pass",
                "run_id": "run-legacy",
                "branch": branch,
                "task_id": "task-legacy",
            }
        ],
    }
    monkeypatch.setattr(
        "modstore_server.self_maintenance_loop_runner._load_loop_memory",
        lambda: memory,
    )

    assert pending_automated_remediation() == {
        "branch": branch,
        "reason": "structured_qa_target_branch_unavailable",
        "run_id": "run-legacy",
        "task_id": "task-legacy",
    }


def test_pending_remediation_prefers_latest_executable_failed_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = {
        "open_items": [
            {
                "kind": "automated_remediation",
                "reason": "structured_review_blocking_findings",
                "run_id": "older-run",
                "branch": "devfleet/trae/older",
                "task_id": "older-task",
            },
            {
                "kind": "failed_steps",
                "run_id": "latest-run",
                "branch": "devfleet/cursor/latest",
                "para_task_id": "latest-task",
                "retry_count": 1,
                "steps": ["review"],
            },
        ]
    }
    monkeypatch.setattr(
        "modstore_server.self_maintenance_loop_runner._load_loop_memory",
        lambda: memory,
    )

    assert pending_automated_remediation() == {
        "branch": "devfleet/cursor/latest",
        "reason": "failed_steps:review",
        "run_id": "latest-run",
        "steps": ["review"],
        "task_id": "latest-task",
    }


def test_pending_remediation_prioritizes_incident_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = {
        "open_items": [
            {
                "kind": "automated_remediation",
                "reason": "structured_review_blocking_findings",
                "run_id": "incident-run",
                "branch": "devfleet/cursor/incident",
                "task_id": "incident-task",
            },
            {
                "kind": "failed_steps",
                "run_id": "newer-run",
                "branch": "devfleet/cursor/newer",
                "para_task_id": "newer-task",
                "retry_count": 1,
                "steps": ["review"],
            },
        ]
    }
    monkeypatch.setattr(
        "modstore_server.self_maintenance_loop_runner._load_loop_memory",
        lambda: memory,
    )
    monkeypatch.setattr(
        "modstore_server.autonomy_scheduler._remediation_lineage_by_run_id",
        lambda: {
            "incident-run": {
                "origin_run_id": "incident-run",
                "origin_triggered_by": "incident_event",
                "origin_reason": "",
            }
        },
    )

    assert pending_automated_remediation() == {
        "branch": "devfleet/cursor/incident",
        "origin_run_id": "incident-run",
        "origin_triggered_by": "incident_event",
        "reason": "structured_review_blocking_findings",
        "run_id": "incident-run",
        "task_id": "incident-task",
    }


def test_pending_remediation_skips_exhausted_failed_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = {
        "open_items": [
            {
                "kind": "failed_steps",
                "run_id": "run-42",
                "branch": "devfleet/cursor/review",
                "para_task_id": "task-42",
                "retry_count": 3,
                "steps": ["review"],
            }
        ]
    }
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MAX_RETRIES", "3")
    monkeypatch.setattr(
        "modstore_server.self_maintenance_loop_runner._load_loop_memory",
        lambda: memory,
    )

    assert pending_automated_remediation() is None


def test_pending_remediation_resumes_without_force(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "modstore_server.autonomy_scheduler.pending_automated_remediation",
        lambda: {
            "branch": "devfleet/trae/fix-42",
            "reason": "structured_review_blocking_findings",
            "run_id": "run-42",
            "task_id": "task-42",
        },
    )
    calls: list[dict] = []

    def _run_self_maintenance_loop(**kwargs):
        calls.append(kwargs)
        return {"status": "completed_merge_requested", "run_id": "run-43"}

    monkeypatch.setattr(
        "modstore_server.self_maintenance_loop_runner.run_self_maintenance_loop",
        _run_self_maintenance_loop,
    )

    assert run_pending_automated_remediation()["status"] == "completed_merge_requested"
    assert calls == [
        {
            "triggered_by": "automated_remediation",
            "force": False,
            "reason": "resume:structured_review_blocking_findings",
            "remediation_context": {
                "branch": "devfleet/trae/fix-42",
                "reason": "structured_review_blocking_findings",
                "run_id": "run-42",
                "task_id": "task-42",
            },
        }
    ]


def test_pending_retort_clarification_is_deferred_for_scheduler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "modstore_server.autonomy_scheduler.pending_automated_remediation",
        lambda: {
            "branch": "devfleet/trae/needs-clarification",
            "reason": "retort_scope_too_large",
            "run_id": "run-retort",
            "task_id": "task-retort",
        },
    )
    monkeypatch.setattr(
        "modstore_server.self_maintenance_loop_runner.run_self_maintenance_loop",
        lambda **_kwargs: {
            "status": "failed",
            "error": "retort_clarification_pending",
        },
    )

    result = run_pending_automated_remediation()

    assert result["status"] == "failed"  # Preserve the loop's own veto receipt.
    assert result["scheduler_status"] == "deferred"
    assert result["scheduler_reason"] == "retort_clarification_pending"


def test_pending_unexpected_remediation_failure_still_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "modstore_server.autonomy_scheduler.pending_automated_remediation",
        lambda: {
            "branch": "devfleet/trae/broken",
            "reason": "structured_review_blocking_findings",
            "run_id": "run-broken",
            "task_id": "task-broken",
        },
    )
    monkeypatch.setattr(
        "modstore_server.self_maintenance_loop_runner.run_self_maintenance_loop",
        lambda **_kwargs: {"status": "failed", "error": "execution_timeout"},
    )

    with pytest.raises(
        RuntimeError, match="automated self-maintenance remediation failed: execution_timeout"
    ):
        run_pending_automated_remediation()


def test_remediation_scheduler_records_retort_hold_as_deferred(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[dict] = []
    monkeypatch.setattr(
        "modstore_server.autonomy_scheduler.register_founder_scorecard_job",
        lambda _scheduler: None,
    )
    monkeypatch.setattr(
        "modstore_server.autonomy_scheduler.run_pending_automated_remediation",
        lambda: {
            "status": "failed",
            "scheduler_status": "deferred",
            "scheduler_reason": "retort_clarification_pending",
        },
    )
    monkeypatch.setattr(
        "modstore_server.scheduler_runtime.record_job_run",
        lambda **kwargs: records.append(kwargs),
    )
    scheduler = MagicMock()

    register_autonomy_jobs(scheduler)
    remediation_job = scheduler.add_job.call_args.args[0]
    remediation_job()

    assert records[-1]["job_id"] == "self_maintenance_remediation_loop"
    assert records[-1]["status"] == "deferred"
    assert records[-1]["error"] == "retort_clarification_pending"


def test_no_pending_remediation_does_not_start_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "modstore_server.autonomy_scheduler.pending_automated_remediation",
        lambda: None,
    )
    started = MagicMock()
    monkeypatch.setattr(
        "modstore_server.self_maintenance_loop_runner.run_self_maintenance_loop",
        started,
    )

    assert run_pending_automated_remediation() == {
        "ok": True,
        "status": "skipped_no_pending_remediation",
    }
    started.assert_not_called()


def test_registers_scorecard_and_remediation_as_single_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "modstore_server.autonomy_scheduler.register_founder_scorecard_job",
        lambda scheduler: scheduler.add_job(
            lambda: None,
            "interval",
            id="founder_scorecard_refresh",
        ),
    )
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_REMEDIATION_INTERVAL_MINUTES", "20")
    scheduler = MagicMock()

    register_autonomy_jobs(scheduler)

    assert scheduler.add_job.call_count == 2
    kwargs = scheduler.add_job.call_args.kwargs
    assert kwargs["id"] == "self_maintenance_remediation_loop"
    assert kwargs["replace_existing"] is True
    assert kwargs["coalesce"] is True
    assert kwargs["max_instances"] == 1
    assert str(scheduler.add_job.call_args.args[1]) == "interval[0:20:00]"


def test_cross_stack_rollout_grace_is_anchored_to_release_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    built_at = datetime.now(timezone.utc)
    manifest = tmp_path / ".xcmax-release.json"
    manifest.write_text(
        json.dumps(
            {
                "built_at": built_at.isoformat(),
                "git_sha": "a" * 40,
                "release_id": "a" * 40,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODSTORE_DEPLOY_TIER", "production")
    monkeypatch.setenv("MODSTORE_RELEASE_MANIFEST", str(manifest))
    monkeypatch.setenv("MODSTORE_AUTONOMY_ROLLOUT_GRACE_SECONDS", "600")
    monkeypatch.setattr(
        "modstore_server.autonomy_scheduler.register_founder_scorecard_job",
        lambda _scheduler: None,
    )
    scheduler = MagicMock()
    recovery_deadlines: dict[str, datetime] = {}

    register_autonomy_jobs(scheduler, recovery_deadlines)

    expected = built_at.timestamp() + 600
    assert recovery_deadlines["founder_scorecard_refresh"].timestamp() == pytest.approx(
        expected, abs=1
    )
    assert (
        recovery_deadlines["self_maintenance_remediation_loop"]
        == recovery_deadlines["founder_scorecard_refresh"]
    )


def test_remediation_job_is_required_and_critical() -> None:
    from modstore_server.workflow_scheduler import (
        _CRITICAL_RUNTIME_JOB_TO_SCHEDULER_ID,
        required_scheduler_job_ids,
    )

    assert "self_maintenance_remediation_loop" in required_scheduler_job_ids()
    assert (
        _CRITICAL_RUNTIME_JOB_TO_SCHEDULER_ID["self_maintenance_remediation_loop"]
        == "self_maintenance_remediation_loop"
    )
