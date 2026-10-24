"""Transaction behavior with isolated services, without facade monkeypatching."""

from __future__ import annotations

import copy
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from modstore_server.maintenance_loop import decision, status_contract
from modstore_server.maintenance_loop.coordinator import MaintenanceRuntime
from modstore_server.maintenance_loop.runtime_dependencies import (
    RuntimeExecution,
    RuntimePolicy,
    RuntimePrompts,
    RuntimeRecovery,
    RuntimeState,
)
from modstore_server.platform_llm_scope import platform_llm_scope_active


class RuntimeHarness:
    def __init__(self, owner, *, barrier=None, fail_step=None, admitted=True, lease_available=True):
        self.owner = owner
        self.memory = {"owner": owner}
        self.ledger = []
        self.calls = []
        self.outcomes = []
        self.events = []
        self.lock = threading.Lock()
        self.sequence = 0

        @contextmanager
        def lease():
            acquired = lease_available and self.lock.acquire(blocking=False)
            self.events.append("lease")
            try:
                yield acquired
            finally:
                if acquired:
                    self.lock.release()
                self.events.append("release")

        def recover_stale(**kwargs):
            assert self.lock.locked()
            assert kwargs == {"exclusive_lease_reacquired": True}
            self.events.append("recover")
            return {}

        def run_step(**kwargs):
            assert platform_llm_scope_active()
            assert self.lock.locked()
            self.calls.append(copy.deepcopy(kwargs))
            if barrier is not None and kwargs["step_name"] == "code":
                barrier.wait(timeout=5)
            ok = kwargs["step_name"] != fail_step
            return (
                {"self_maintenance_retry_attempts": 1},
                ok,
                "" if ok else "independent_review_rejected",
                {"task_id": f"task-{owner}", "branch": f"branch-{owner}"},
                f"report-{owner}",
                0,
                0,
            )

        def record_outcome(final, gate):
            assert gate["owner"] == owner
            self.outcomes.append(copy.deepcopy(final))
            self.memory["last_run"] = final["run_id"]

        def decide(**kwargs):
            self.events.append("decide")
            if kwargs["status"] != "completed":
                # Exercise the real fail-closed decision before any external policy IO.
                return decision._decide_post_loop_policy(**kwargs)
            assert [step["step"] for step in kwargs["steps"]] == ["code", "review", "qa"]
            return {"action": "auto_merge_requested_low_risk"}

        def new_run_id():
            self.sequence += 1
            return f"run-{owner}-{self.sequence}"

        self.runtime = MaintenanceRuntime(
            state=RuntimeState(
                lease=lease,
                ensure_baseline=lambda: {},
                load_memory=lambda: copy.deepcopy(self.memory),
                write_memory=lambda memory: self.memory.update(copy.deepcopy(memory)),
                memory_path=lambda: Path(owner) / "memory.json",
                append=lambda row: self.ledger.append(copy.deepcopy(row)),
                record_outcome=record_outcome,
            ),
            recovery=RuntimeRecovery(
                stale_runs=recover_stale,
                requested_merges=lambda _memory: {},
                retort_scope=lambda _memory: {},
                absorbed_merges=lambda _memory, **_kwargs: {},
            ),
            policy=RuntimePolicy(
                admit=lambda **_kwargs: {
                    "should_run": admitted,
                    "reason": "test_admission",
                    "owner": owner,
                },
                actor_user_id=lambda: len(owner),
                decide=decide,
            ),
            execution=RuntimeExecution(
                run_step=run_step,
                retort_before_review=lambda **_kwargs: {"blocked": False},
                validate_branch_delivery=lambda **_kwargs: {"ok": True},
                validate_knowledge=lambda **_kwargs: {"ok": True},
                reject_knowledge=lambda **_kwargs: pytest.fail("unexpected KB rejection"),
            ),
            prompts=RuntimePrompts(
                code=lambda _run, _gate, memory, _candidate: f"code:{memory['owner']}",
                review=lambda _run, branch, memory: f"review:{memory['owner']}:{branch}",
                qa=lambda _run, branch, memory: f"qa:{memory['owner']}:{branch}",
            ),
            now=lambda: datetime(2026, 10, 22, tzinfo=timezone.utc),
            new_run_id=new_run_id,
        )


def test_two_overlapping_runtimes_keep_state_dispatch_and_platform_scope_isolated():
    barrier = threading.Barrier(2)
    first = RuntimeHarness("first", barrier=barrier)
    second = RuntimeHarness("second", barrier=barrier)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(harness.runtime.run) for harness in (first, second)]
        results = [future.result(timeout=10) for future in futures]

    assert not platform_llm_scope_active()
    for harness, result in zip((first, second), results):
        owner = harness.owner
        assert result["status"] == "completed_merge_requested"
        assert result["branch"] == f"branch-{owner}"
        assert result["para_task_id"] == f"task-{owner}"
        assert {row["run_id"] for row in harness.ledger} == {f"run-{owner}-1"}
        assert harness.memory == {"owner": owner, "last_run": f"run-{owner}-1"}
        assert [row["phase"] for row in harness.ledger] == [
            "start",
            "step",
            "step",
            "step",
            "complete",
        ]
        assert len(harness.outcomes) == 1
        assert harness.events == ["lease", "recover", "decide", "release"]
        assert all(call["user_id"] == len(owner) for call in harness.calls)
        assert harness.calls[0]["task_text"] == f"code:{owner}"
        for call in harness.calls[1:]:
            assert call["extra"]["report_only"] is True
            assert call["extra"]["review_target_branch"] == f"branch-{owner}"
            assert call["extra"]["review_target_para_task_id"] == f"task-{owner}"
            assert call["task_text"].endswith(f":{owner}:branch-{owner}")
    assert results[0]["steps"] is not results[1]["steps"]


def test_repeated_runtime_transactions_do_not_reuse_step_or_branch_state():
    harness = RuntimeHarness("repeat")
    first = harness.runtime.run()
    second = harness.runtime.run()
    assert first["run_id"] == "run-repeat-1"
    assert second["run_id"] == "run-repeat-2"
    assert first["steps"] is not second["steps"]
    assert len(first["steps"]) == len(second["steps"]) == 3
    assert all(step["run_id"] == first["run_id"] for step in first["steps"])
    assert "para_task_id" not in harness.calls[3]["extra"]
    assert harness.memory["last_run"] == second["run_id"]


@pytest.mark.parametrize("lease_available,admitted", [(False, True), (True, False)])
def test_lease_and_admission_denials_never_dispatch_or_finalize_memory(lease_available, admitted):
    harness = RuntimeHarness("blocked", lease_available=lease_available, admitted=admitted)
    result = harness.runtime.run(force=True, reason="test")
    expected = "skipped_active_lease" if not lease_available else "skipped_test_admission"
    assert result["status"] == expected
    assert harness.calls == harness.outcomes == []
    assert [row["phase"] for row in harness.ledger] == ["skip"]
    assert ("recover" in harness.events) is lease_available
    assert not platform_llm_scope_active()


def test_failed_review_stops_qa_and_records_one_failed_terminal_outcome():
    harness = RuntimeHarness("reject", fail_step="review")
    result = harness.runtime.run()
    assert [call["step_name"] for call in harness.calls] == ["code", "review"]
    assert result["status"] == "failed"
    assert result["failed_step"] == "review"
    assert result["policy_decision"] == {"action": "stop", "reason": "loop_not_completed"}
    assert len(harness.outcomes) == 1
    assert len([row for row in harness.ledger if row["phase"] == "complete"]) == 1
    assert not harness.lock.locked()


@pytest.mark.parametrize("scope_only", [False, True])
def test_retort_blocks_before_report_dispatch_and_preserves_scope_remediation(scope_only):
    harness = RuntimeHarness("retort")
    gate = {"blocked": True, "reason": "retort_clarification_pending"}
    if scope_only:
        gate["clarification"] = {"questions": [{"reason": "elevated_risk_or_large_diff"}]}
    harness.runtime.execution = replace(
        harness.runtime.execution, retort_before_review=lambda **_kwargs: gate
    )
    result = harness.runtime.run()
    assert [call["step_name"] for call in harness.calls] == ["code"]
    assert result["failed_step"] == "review"
    assert result["retort_clarification"] == gate
    assert result["status"] == "failed"
    expected = "hold_for_automated_remediation" if scope_only else "stop"
    assert result["policy_decision"]["action"] == expected
    assert len(harness.outcomes) == 1
    if scope_only:
        assert result["policy_decision"]["resume_from_clean_baseline"] is True
        assert "decide" not in harness.events


def test_knowledge_schema_rejection_stops_before_review_and_owns_retry_receipt():
    harness = RuntimeHarness("knowledge")
    received = []
    harness.runtime.execution = replace(
        harness.runtime.execution,
        validate_knowledge=lambda **_kwargs: {
            "ok": False,
            "reason": "kb_json_schema_validation_failed",
            "kb_validation": {"errors": ["missing schema field"]},
        },
        reject_knowledge=lambda **kwargs: received.append(kwargs) or {"status": "kb_schema_failed"},
    )
    assert harness.runtime.run() == {"status": "kb_schema_failed"}
    assert [call["step_name"] for call in harness.calls] == ["code"]
    assert received[0]["branch"] == "branch-knowledge"
    assert received[0]["para_task_id"] == "task-knowledge"
    assert harness.outcomes == []
    assert "decide" not in harness.events
    assert not harness.lock.locked()


def test_runtime_components_cold_import_without_public_facade_bootstrap():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "from modstore_server.maintenance_loop import coordinator, status, decision; "
                "assert 'modstore_server.self_maintenance_loop_runner' not in sys.modules"
            ),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_status_participants_sort_by_each_participant_without_scratch_loop_state(monkeypatch):
    monkeypatch.setattr(status_contract.review, "_focused_test_command", lambda: "pytest")
    state = {
        "trigger": "cron",
        "gate": {},
        "generated_at": "2026-10-22T00:00:00Z",
        "latest_complete": None,
        "latest_skip": None,
        "open_run_ids": ["run-a", "run-b"],
        "rows": [],
        "milestone_rows": [],
        "evidence_window_days": 30,
        "evidence_scan_limit": 5000,
        "evidence_run_limit": 24,
        "steps_by_run": {"run-a": [{"step": "code"}], "run-b": [{"step": "qa"}]},
        "participants_by_id": {
            "older": {"employee_id": "older", "latest_at": "2026-10-20T00:00:00Z"},
            "newer": {"employee_id": "newer", "latest_at": "2026-10-22T00:00:00Z"},
        },
        "run_timelines": [],
        "roster_alignment": {},
        "ui_bridge": {},
        "active_gates": {},
        "governance_gate_current": {},
        "governance_audit_summary": {},
        "governance_audit": [],
        "merge_decision": {},
        "kb_summary": {},
        "evolution_metrics_summary": {},
        "memory": {},
        "open_items": [],
        "recent_runs": [],
    }
    result = status_contract._build_runtime_status_result(
        state=state,
        runtime_contract={"schema_version": "self_maintenance_runtime.v1"},
        contract_validation={},
        contract_status={},
        runtime_source={},
        latest_event_at=None,
    )
    assert [item["employee_id"] for item in result["participants"]] == ["newer", "older"]
    assert result["evidence"]["steps_by_open_run"] == state["steps_by_run"]
    assert "item" not in state and "run_id" not in state


def test_runtime_status_projects_complete_read_model_without_previous_call_state(monkeypatch):
    from modstore_server import duty_employee_registry, duty_roster, self_evolution_knowledge
    from modstore_server.maintenance_loop import config, review, schedule, status, store

    employees = ["vibe-coding-maintainer", "change-request-auditor", "test-qa-runner"]
    rows = [{"phase": "start", "run_id": "visible", "created_at": "2026-10-22T00:00:00Z"}]
    rows.extend(
        {
            "phase": "step",
            "run_id": "visible",
            "employee_id": employee,
            "step": step,
            "ok": True,
            "timestamp": f"2026-10-22T00:0{index}:00Z",
        }
        for index, (employee, step) in enumerate(zip(employees, ("code", "review", "qa")), 1)
    )
    monkeypatch.setattr(config, "_utc_now", lambda: datetime(2026, 10, 22, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(store, "_read_ledger", lambda **_kwargs: copy.deepcopy(rows))
    monkeypatch.setattr(store, "_load_loop_memory", lambda: {})
    monkeypatch.setattr(store, "_read_governance_audit", lambda _limit: [])
    monkeypatch.setattr(
        schedule, "should_run_self_maintenance_loop", lambda **_kwargs: {"should_run": False}
    )
    monkeypatch.setattr(review, "_focused_test_command", lambda: "pytest")
    monkeypatch.setattr(duty_roster, "all_planned_employee_ids", lambda: employees)
    monkeypatch.setattr(duty_roster, "SIX_LINE_DEPARTMENTS", {"test": {"ids": employees}})
    monkeypatch.setattr(
        duty_employee_registry, "duty_employee_records", lambda: dict.fromkeys(employees, {})
    )
    monkeypatch.setattr(
        self_evolution_knowledge, "build_self_evolution_context", lambda **_kwargs: {}
    )
    monkeypatch.setattr(
        self_evolution_knowledge, "evolution_metrics_gate", lambda: {"pause": False}
    )

    first = status.get_self_maintenance_runtime_status()
    assert first["schema_version"] == "self_maintenance_runtime.v1"
    assert first["contract_validation"]["ok"] is True
    assert [item["employee_id"] for item in first["participants"]] == list(reversed(employees))
    assert first["roster_alignment"]["gate"]["ok"] is True
    assert list(first["evidence"]["steps_by_open_run"]) == ["visible"]
    rows.clear()
    second = status.get_self_maintenance_runtime_status()
    assert second["participants"] == []
    assert second["run_timelines"] == []
    assert second["evidence"]["steps_by_open_run"] == {}
    assert len(first["participants"]) == 3


def test_public_entry_point_preserves_arguments_and_uses_runtime_composition(monkeypatch):
    from modstore_server import self_maintenance_loop_runner
    from modstore_server.maintenance_loop import coordinator

    harness = RuntimeHarness("public")
    monkeypatch.setattr(coordinator, "MaintenanceRuntime", lambda: harness.runtime)
    result = self_maintenance_loop_runner.run_self_maintenance_loop(
        triggered_by="api", force=True, reason="explicit maintenance"
    )
    assert result["triggered_by"] == "api"
    assert harness.ledger[0]["force"] is True
    assert harness.ledger[0]["reason"] == "explicit maintenance"
    assert all(
        callable(getattr(self_maintenance_loop_runner, name))
        for name in self_maintenance_loop_runner.__all__
    )
