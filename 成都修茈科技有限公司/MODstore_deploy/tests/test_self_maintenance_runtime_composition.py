"""Transaction behavior with isolated services, without facade monkeypatching."""

from __future__ import annotations

import copy
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timezone
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
    def __init__(
        self,
        owner,
        *,
        barrier=None,
        fail_step=None,
        admitted=True,
        lease_available=True,
    ):
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

        def write_memory(memory):
            # Production replaces the JSON snapshot, including removed keys.
            self.memory = copy.deepcopy(memory)

        def decide(**kwargs):
            self.events.append("decide")
            if kwargs["status"] != "completed":
                # Exercise the real fail-closed decision before any external policy IO.
                return decision._decide_post_loop_policy(**kwargs)
            assert [step["step"] for step in kwargs["steps"]] == [
                "code",
                "review",
                "qa",
            ]
            return {"action": "auto_merge_requested_low_risk"}

        def new_run_id():
            self.sequence += 1
            return f"run-{owner}-{self.sequence}"

        self.runtime = MaintenanceRuntime(
            state=RuntimeState(
                lease=lease,
                ensure_baseline=lambda: {},
                load_memory=lambda: copy.deepcopy(self.memory),
                write_memory=write_memory,
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
                review=lambda _run, branch, memory: (f"review:{memory['owner']}:{branch}"),
                qa=lambda _run, branch, memory: f"qa:{memory['owner']}:{branch}",
            ),
            now=lambda: datetime(2026, 10, 22, tzinfo=UTC),
            new_run_id=new_run_id,
        )


@pytest.mark.parametrize(
    "reason,expected",
    [
        ("cooldown", 1),
        ("below_threshold", 1),
        ("disabled", 0),
        ("runtime_provenance_blocked", 0),
        ("evolution_metrics_pause", 0),
    ],
)
def test_pending_merge_readback_survives_new_work_throttle_without_weakening_gates(
    reason, expected
):
    harness = RuntimeHarness("pending", admitted=False)
    calls = []

    def reconcile(memory):
        assert harness.lock.locked()
        calls.append(memory["owner"])
        memory["delivery_readback"] = "pending"
        return {"changed": True, "merged": 1}

    harness.runtime.policy = replace(
        harness.runtime.policy, admit=lambda **_kwargs: {"should_run": False, "reason": reason}
    )
    harness.runtime.recovery = replace(harness.runtime.recovery, requested_merges=reconcile)
    result = harness.runtime.run()
    assert len(calls) == expected
    assert harness.calls == []
    assert result["status"] == f"skipped_{reason}"
    assert (harness.memory.get("delivery_readback") == "pending") == bool(expected)


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


@pytest.mark.parametrize("cloud_device", [None, "   "])
def test_cloud_opt_in_without_device_fails_without_dispatch(monkeypatch, cloud_device):
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_DOT_MAILBOX", "1")
    monkeypatch.setenv("MODSTORE_PARA_DEVICE_ID", "legacy-mac")
    if cloud_device is None:
        monkeypatch.delenv("MODSTORE_SELF_MAINTENANCE_DEVICE_ID", raising=False)
    else:
        monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_DEVICE_ID", cloud_device)
    harness = RuntimeHarness("missing-cloud-device")

    result = harness.runtime.run()

    assert harness.calls == []
    assert result["status"] == "failed"
    assert result["failed_step"] == "code"
    assert (
        result["error"] == "MODSTORE_SELF_MAINTENANCE_DEVICE_ID is required for dot mailbox routing"
    )
    assert [row["phase"] for row in harness.ledger] == ["start", "complete"]
    assert harness.outcomes == [result]
    assert not harness.lock.locked()


def test_failed_review_stops_qa_and_records_one_failed_terminal_outcome():
    harness = RuntimeHarness("reject", fail_step="review")
    result = harness.runtime.run()
    assert [call["step_name"] for call in harness.calls] == ["code", "review"]
    assert result["status"] == "failed"
    assert result["failed_step"] == "review"
    assert result["policy_decision"] == {
        "action": "stop",
        "reason": "loop_not_completed",
    }
    assert len(harness.outcomes) == 1
    assert len([row for row in harness.ledger if row["phase"] == "complete"]) == 1
    assert not harness.lock.locked()


@pytest.mark.parametrize("failed_step", ["code", "review", "qa"])
def test_terminal_failure_resumes_with_fresh_request_and_original_code_target(
    failed_step, tmp_path, monkeypatch
):
    from modstore_server.maintenance_loop import outcomes, store

    path = tmp_path / "memory.json"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(path))
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_LEDGER", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_RESUME_REVIEW_QA", "1")
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MAX_RETRIES", "3")
    for name in ("record_loop_evolution_knowledge", "salvage_kb_from_workspace"):
        monkeypatch.setattr(outcomes.self_evolution_knowledge, name, lambda *args, **kwargs: {})
    harness = RuntimeHarness("terminal-retry", fail_step=failed_step)
    store._write_loop_memory(harness.memory)
    harness.runtime.state = replace(
        harness.runtime.state,
        load_memory=store._load_loop_memory,
        write_memory=store._write_loop_memory,
        memory_path=lambda: path,
        record_outcome=outcomes._update_loop_memory,
    )
    harness.runtime.policy = replace(
        harness.runtime.policy, decide=lambda **kwargs: {"action": "stop"}
    )
    execute = harness.runtime.execution.run_step

    def run_step(**kwargs):
        result, ok, error, _, report, code_retries, marker_retries = execute(**kwargs)
        step = kwargs["step_name"]
        attempt = sum(call["step_name"] == step for call in harness.calls)
        code_attempt = sum(call["step_name"] == "code" for call in harness.calls)
        persisted = store._load_loop_memory()["pending_execution"]
        assert persisted["request_id"] == kwargs["extra"]["request_id"]
        if attempt > 1:
            ok, error = True, ""
        para = {"task_id": f"task-{step}-{attempt}", "branch": f"branch-code-{code_attempt}"}
        return result, ok, error, para, report, code_retries, marker_retries

    harness.runtime.execution = replace(harness.runtime.execution, run_step=run_step)
    first = harness.runtime.run()
    assert first["status"] == "failed" and first["failed_step"] == failed_step
    memory = store._load_loop_memory()
    assert "pending_execution" not in memory
    failed_items = [item for item in memory["open_items"] if item["kind"] == "failed_steps"]
    assert len(failed_items) == 1 and failed_items[0]["steps"] == [failed_step]
    assert failed_items[0]["run_id"] == first["run_id"]
    previous_calls = list(harness.calls)

    restarted = MaintenanceRuntime(
        state=harness.runtime.state,
        recovery=harness.runtime.recovery,
        policy=harness.runtime.policy,
        execution=harness.runtime.execution,
        prompts=harness.runtime.prompts,
        now=harness.runtime.now,
        new_run_id=lambda: "after-terminal-failure",
    )
    second = restarted.run()
    next_calls = harness.calls[len(previous_calls) :]
    order = ["code", "review", "qa"]
    assert second["status"] == "completed"
    assert second["resume_candidate"]["failed_run_id"] == first["run_id"]
    assert [call["step_name"] for call in next_calls] == order[order.index(failed_step) :]
    assert {call["extra"]["request_id"] for call in previous_calls}.isdisjoint(
        call["extra"]["request_id"] for call in next_calls
    )
    assert all("para_task_id" not in call["extra"] for call in next_calls)
    if failed_step == "code":
        assert second["para_task_id"] != first["para_task_id"]
        assert "branch" not in next_calls[0]["extra"]
    else:
        assert second["para_task_id"] == first["para_task_id"]
        assert second["branch"] == first["branch"]
        assert all(
            call["extra"]["review_target_para_task_id"] == first["para_task_id"]
            and call["extra"]["review_target_branch"] == first["branch"]
            for call in next_calls
        )
    assert "pending_execution" not in store._load_loop_memory()


@pytest.mark.parametrize("pending_step", ["code", "review", "qa"])
def test_restart_reconciles_exact_pending_step_before_downstream_work(
    pending_step, tmp_path, monkeypatch
):
    from modstore_server.maintenance_loop import results, store

    memory_path = tmp_path / "memory.json"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(memory_path))
    harness = RuntimeHarness("durable")
    store._write_loop_memory(harness.memory)
    state = replace(
        harness.runtime.state,
        load_memory=store._load_loop_memory,
        write_memory=store._write_loop_memory,
        memory_path=lambda: memory_path,
        record_outcome=lambda *args: None,
    )
    harness.runtime.state = state
    calls = []
    submitted = set()

    def run_step(**kwargs):
        step = kwargs["step_name"]
        calls.append((step, kwargs["extra"].get("para_task_id")))
        persisted = store._load_loop_memory()["pending_execution"]
        assert persisted["step"] == step
        assert persisted["request_id"] == kwargs["extra"]["request_id"]
        # External boundary: new submission happens once; subsequent call is readback.
        waiting = step == pending_step and step not in submitted
        if not kwargs["extra"].get("para_task_id"):
            assert step not in submitted
            submitted.add(step)
        else:
            assert kwargs["extra"]["para_task_id"] == f"task-{step}"
            assert step in submitted
        output = {
            "handler": "para_delegate",
            "task_id": f"task-{step}",
            "ok": True,
            "accepted": True,
            "completed": not waiting,
            "status": "para_task_accepted" if waiting else "para_task_completed",
            "para_result": {
                "task_id": f"task-{step}",
                "subtasks": [{"id": f"sub-{step}", "branch": "branch-durable"}],
            },
        }
        value = {"result": {"outputs": [output]}}
        return value, not waiting, "", results._extract_para_meta(value), "report", 0, 0

    harness.runtime.execution = replace(harness.runtime.execution, run_step=run_step)
    first = harness.runtime.run()
    assert first["status"] == "waiting_reconciliation"
    assert first["steps"][-1]["requires_reconciliation"] is True
    original = store._load_loop_memory()["pending_execution"]
    assert original["task_id"] == f"task-{pending_step}"
    assert original["code_task_id"] == "task-code"
    assert submitted == set(
        ["code", "review", "qa"][: ["code", "review", "qa"].index(pending_step) + 1]
    )

    # A new runtime reads only the existing memory and resumes the original task.
    restarted = MaintenanceRuntime(
        state=state,
        recovery=harness.runtime.recovery,
        policy=harness.runtime.policy,
        execution=harness.runtime.execution,
        prompts=harness.runtime.prompts,
        now=harness.runtime.now,
        new_run_id=lambda: "after-restart",
    )
    if pending_step == "review":
        restarted.execution = replace(
            restarted.execution,
            validate_knowledge=lambda **kwargs: pytest.fail("must read original review first"),
            retort_before_review=lambda **kwargs: pytest.fail("must not replace pending review"),
        )
    second = restarted.run()
    assert second["status"] == "completed_merge_requested"
    assert second["para_task_id"] == "task-code"
    assert [s["step"] for s in second["steps"]] == ["code", "review", "qa"]
    assert calls.count((pending_step, f"task-{pending_step}")) == 1
    assert submitted == {"code", "review", "qa"}
    assert "pending_execution" not in store._load_loop_memory()


@pytest.mark.parametrize(
    "pending",
    [
        {"user_id": 7, "step": "code", "task_id": ""},
        {"user_id": 999, "step": "code", "task_id": "original"},
        {"user_id": 7, "step": "invalid", "task_id": "original"},
    ],
)
def test_unbound_pending_execution_blocks_even_forced_remediation(pending):
    harness = RuntimeHarness("durable")
    harness.memory["pending_execution"] = pending
    result = harness.runtime.run(force=True, remediation_context={"run_id": "new-request"})
    assert result["status"] == "waiting_reconciliation"
    assert result["reason"] == "pending_execution_identity_unavailable"
    assert harness.calls == harness.outcomes == []
    assert harness.memory["pending_execution"] == pending


@pytest.mark.parametrize("known_reason", [False, True])
def test_pending_identity_error_exposes_only_known_codes(monkeypatch, known_reason):
    from modstore_server.maintenance_loop import resume

    harness = RuntimeHarness("durable")
    pending = {"task_id": "original-task"}
    harness.memory["pending_execution"] = pending
    private_detail = "internal journal configuration at /private/runtime/settings.json"

    def unavailable(*_args):
        raise ValueError("pending_execution_actor_mismatch" if known_reason else private_detail)

    monkeypatch.setattr(resume, "_pending_execution_candidate", unavailable)
    result = harness.runtime.run(force=True)
    assert result["status"] == "waiting_reconciliation"
    assert result["requires_reconciliation"] is True
    assert result["reconciliation_reason"] == (
        "pending_execution_actor_mismatch"
        if known_reason
        else "pending_execution_identity_unavailable"
    )
    assert private_detail not in repr(result)
    assert harness.ledger[-1] == result
    assert harness.calls == harness.outcomes == []
    assert harness.memory["pending_execution"] == pending


def test_dispatch_exception_preserves_durable_intent_and_prevents_restart_replay():
    harness = RuntimeHarness("lost")
    attempts = []

    def lost_reply(**kwargs):
        assert harness.memory["pending_execution"]["step"] == "code"
        attempts.append(kwargs)
        raise RuntimeError("remote reply lost")

    harness.runtime.execution = replace(harness.runtime.execution, run_step=lost_reply)
    first = harness.runtime.run()
    second = harness.runtime.run(force=True)
    assert first["status"] == "failed"
    assert second["status"] == "waiting_reconciliation"
    assert len(attempts) == 1


@pytest.mark.parametrize("raw", ["{broken", "[]"])
def test_unreadable_memory_never_authorizes_new_execution(raw, tmp_path, monkeypatch):
    from modstore_server.maintenance_loop import store

    path = tmp_path / "memory.json"
    path.write_text(raw)
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(path))
    harness = RuntimeHarness("corrupt")
    harness.runtime.state = replace(harness.runtime.state, load_memory=store._load_loop_memory)
    result = harness.runtime.run(force=True)
    assert result["status"] == "waiting_reconciliation"
    assert harness.calls == harness.outcomes == []
    assert path.read_text() == raw


@pytest.mark.parametrize("crash_after", ["code", "review", "qa"])
def test_confirmed_checkpoint_survives_process_death_between_steps(
    crash_after, tmp_path, monkeypatch
):
    from modstore_server.maintenance_loop import store

    path = tmp_path / "memory.json"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(path))
    harness = RuntimeHarness("checkpoint")
    store._write_loop_memory(harness.memory)
    killed = False

    def write_and_kill(memory):
        nonlocal killed
        store._write_loop_memory(memory)
        pending = memory.get("pending_execution") or {}
        if not killed and pending.get("step") == crash_after and pending.get("state") == "settled":
            killed = True
            raise KeyboardInterrupt("simulated process death after durable receipt")

    harness.runtime.state = replace(
        harness.runtime.state,
        load_memory=store._load_loop_memory,
        write_memory=write_and_kill,
        memory_path=lambda: path,
        record_outcome=lambda *args: None,
    )
    with pytest.raises(KeyboardInterrupt):
        harness.runtime.run()
    assert store._load_loop_memory()["pending_execution"]["state"] == "settled"
    harness.runtime.state = replace(harness.runtime.state, write_memory=store._write_loop_memory)
    final = harness.runtime.run()
    assert final["status"] == "completed_merge_requested"
    assert [call["step_name"] for call in harness.calls] == ["code", "review", "qa"]
    assert "pending_execution" not in store._load_loop_memory()


def test_legacy_review_only_resume_keeps_its_scope_when_original_reply_is_pending(monkeypatch):
    from modstore_server.maintenance_loop import resume

    harness = RuntimeHarness("legacy")
    monkeypatch.setattr(
        resume,
        "_resume_review_qa_candidate",
        lambda memory: {
            "branch": "branch-code",
            "para_task_id": "task-code",
            "failed_steps": ["review"],
            "failed_run_id": "legacy-code-run",
        },
    )
    calls = []

    def run_step(**kwargs):
        calls.append(kwargs)
        waiting = len(calls) == 1
        step = kwargs["step_name"]
        result = {"ok": True, "requires_reconciliation": waiting}
        return result, not waiting, "", {"task_id": f"task-{step}"}, "report", 0, 0

    harness.runtime.execution = replace(harness.runtime.execution, run_step=run_step)
    harness.runtime.policy = replace(
        harness.runtime.policy,
        decide=lambda **kwargs: {
            "action": "stop",
            "steps": [s["step"] for s in kwargs["steps"]],
        },
    )
    assert harness.runtime.run()["status"] == "waiting_reconciliation"
    final = harness.runtime.run()
    assert final["status"] == "completed"
    assert final["policy_decision"]["steps"] == ["review", "qa"]
    assert [call["step_name"] for call in calls] == ["review", "review", "qa"]
    assert calls[1]["extra"]["para_task_id"] == "task-review"
    assert calls[2]["extra"]["review_target_para_task_id"] == "task-code"
    assert "pending_execution" not in harness.memory


@pytest.mark.parametrize(
    "crash_at", ["policy", "finalized", "recording_outcome", "outcome", "foreign", "retort"]
)
def test_finalization_restart_never_replays_policy_or_uncertain_projection(
    crash_at, tmp_path, monkeypatch
):
    from modstore_server.maintenance_loop import store

    path = tmp_path / "memory.json"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(path))
    harness = RuntimeHarness("final-window")
    store._write_loop_memory(harness.memory)
    decide = harness.runtime.policy.decide
    killed = False

    def crash():
        nonlocal killed
        killed = True
        raise KeyboardInterrupt("simulated process death at final side effect boundary")

    def write(memory):
        store._write_loop_memory(memory)
        pending = memory.get("pending_execution") or {}
        boundary = "finalized" if crash_at == "retort" else crash_at
        if not killed and pending.get("state") == boundary:
            crash()

    def policy(**kwargs):
        assert store._load_loop_memory()["pending_execution"]["state"] == "finalizing"
        result = decide(**kwargs)
        if crash_at == "policy":
            crash()
        return result

    def project(final, gate):
        memory = store._load_loop_memory()
        assert memory["pending_execution"]["state"] == "recording_outcome"
        harness.outcomes.append(copy.deepcopy(final))
        memory["last_run"] = {
            **{key: final[key] for key in ("run_id", "branch", "para_task_id", "status")},
            "action": final["policy_decision"]["action"],
        }
        if crash_at == "foreign":
            memory["last_run"]["para_task_id"] = "foreign-task"
        store._write_loop_memory(memory)
        if not killed and crash_at in {"outcome", "foreign"}:
            crash()

    harness.runtime.state = replace(
        harness.runtime.state,
        load_memory=store._load_loop_memory,
        write_memory=write,
        memory_path=lambda: path,
        record_outcome=project,
    )
    harness.runtime.policy = replace(harness.runtime.policy, decide=policy)
    if crash_at == "retort":
        harness.runtime.execution = replace(
            harness.runtime.execution,
            retort_before_review=lambda **kwargs: {
                "blocked": True,
                "reason": "retort_clarification_pending",
            },
        )
    with pytest.raises(KeyboardInterrupt):
        harness.runtime.run()
    harness.runtime.state = replace(harness.runtime.state, write_memory=store._write_loop_memory)
    final = harness.runtime.run(force=True)
    assert harness.events.count("decide") == 1
    assert [call["step_name"] for call in harness.calls] == (
        ["code"] if crash_at == "retort" else ["code", "review", "qa"]
    )
    if crash_at in {"finalized", "outcome", "retort"}:
        assert final["status"] == (
            "failed" if crash_at == "retort" else "completed_merge_requested"
        )
        assert final["run_id"] == "run-final-window-1"
        assert len(harness.outcomes) == 1
        assert "pending_execution" not in store._load_loop_memory()
    else:
        assert final["status"] == "waiting_reconciliation"
        assert len(harness.outcomes) == int(crash_at == "foreign")
        assert "pending_execution" in store._load_loop_memory()


def test_policy_exception_cannot_enter_failed_finalization_and_clear_original_intent():
    harness = RuntimeHarness("policy-error")
    attempts = []

    def policy(**kwargs):
        attempts.append(kwargs)
        raise RuntimeError("merge response lost")

    harness.runtime.policy = replace(harness.runtime.policy, decide=policy)
    first = harness.runtime.run()
    second = harness.runtime.run(force=True)
    assert first["status"] == second["status"] == "waiting_reconciliation"
    assert len(attempts) == 1
    assert harness.outcomes == []
    assert harness.memory["pending_execution"]["state"] == "finalizing"


def test_foreign_readback_never_replaces_the_original_task_or_branch():
    harness = RuntimeHarness("foreign")
    calls = []

    def run_step(**kwargs):
        calls.append(kwargs)
        waiting = len(calls) == 1
        task_id = "original" if waiting else "foreign-task"
        return (
            {"ok": True, "requires_reconciliation": waiting},
            not waiting,
            "",
            {"task_id": task_id, "branch": "original-branch" if waiting else "foreign-branch"},
            "report",
            0,
            0,
        )

    harness.runtime.execution = replace(harness.runtime.execution, run_step=run_step)
    assert harness.runtime.run()["status"] == "waiting_reconciliation"
    final = harness.runtime.run()
    assert final["status"] == "waiting_reconciliation"
    assert final["error"] == "original_execution_identity_mismatch"
    assert len(calls) == 2
    pending = harness.memory["pending_execution"]
    assert pending["task_id"] == pending["code_task_id"] == "original"
    assert pending["branch"] == "original-branch"


def test_resume_rechecks_knowledge_without_repeating_confirmed_code():
    harness = RuntimeHarness("knowledge-recovery")
    checks = []

    def check_knowledge(**kwargs):
        checks.append(kwargs)
        if len(checks) == 1:
            raise RuntimeError("knowledge validation temporarily unavailable")
        return {"ok": True}

    harness.runtime.execution = replace(
        harness.runtime.execution, validate_knowledge=check_knowledge
    )
    assert harness.runtime.run()["status"] == "failed"
    assert harness.memory["pending_execution"]["state"] == "settled"
    final = harness.runtime.run()
    assert final["status"] == "completed_merge_requested"
    assert [call["step_name"] for call in harness.calls] == ["code", "review", "qa"]
    assert len(checks) == 2


@pytest.mark.parametrize("scope_only", [False, True])
def test_retort_blocks_before_report_dispatch_and_preserves_scope_remediation(
    scope_only,
):
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
        reject_knowledge=lambda **kwargs: (
            received.append(kwargs) or {"status": "kb_schema_failed"}
        ),
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


def test_status_participants_sort_by_each_participant_without_scratch_loop_state(
    monkeypatch,
):
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
    assert [item["employee_id"] for item in result["participants"]] == [
        "newer",
        "older",
    ]
    assert result["evidence"]["steps_by_open_run"] == state["steps_by_run"]
    assert "item" not in state and "run_id" not in state


@pytest.mark.parametrize(
    "legacy,receipts,production,expected_envs,half_closed",
    [
        (False, False, False, [], True),
        (True, False, True, [], True),
        (False, True, False, ["staging"], True),
        (False, True, True, ["staging", "production"], False),
    ],
)
def test_runtime_status_projects_complete_read_model_without_previous_call_state(
    monkeypatch,
    legacy,
    receipts,
    production,
    expected_envs,
    half_closed,
):
    from modstore_server import (
        duty_employee_registry,
        duty_roster,
        self_evolution_knowledge,
    )
    from modstore_server.maintenance_loop import config, review, schedule, status, store

    for suffix, enabled in (
        ("AUTO_DISPATCH_DEPLOY", legacy),
        ("DEPLOY_RECEIPTS_ENABLED", receipts),
        ("PRODUCTION_DEPLOY_ENABLED", production),
    ):
        monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_" + suffix, str(int(enabled)))
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
    monkeypatch.setattr(config, "_utc_now", lambda: datetime(2026, 10, 22, 1, tzinfo=UTC))
    monkeypatch.setattr(store, "_read_ledger", lambda **_kwargs: copy.deepcopy(rows))
    monkeypatch.setattr(store, "_load_loop_memory", lambda: {})
    monkeypatch.setattr(store, "_read_governance_audit", lambda _limit: [])
    monkeypatch.setattr(
        schedule,
        "should_run_self_maintenance_loop",
        lambda **_kwargs: {"should_run": False},
    )
    monkeypatch.setattr(review, "_focused_test_command", lambda: "pytest")
    monkeypatch.setattr(duty_roster, "all_planned_employee_ids", lambda: employees)
    monkeypatch.setattr(duty_roster, "SIX_LINE_DEPARTMENTS", {"test": {"ids": employees}})
    monkeypatch.setattr(
        duty_employee_registry,
        "duty_employee_records",
        lambda: dict.fromkeys(employees, {}),
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
    assert first["policy"]["auto_dispatch_deploy_envs"] == expected_envs
    assert first["policy"]["deployment_receipts_enabled"] is receipts
    assert first["l4_closure"]["half_closed_without_deploy"] is half_closed
    rows.clear()
    second = status.get_self_maintenance_runtime_status()
    assert second["participants"] == []
    assert second["run_timelines"] == []
    assert second["evidence"]["steps_by_open_run"] == {}
    assert len(first["participants"]) == 3


def test_public_entry_point_preserves_arguments_and_uses_runtime_composition(
    monkeypatch,
):
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
