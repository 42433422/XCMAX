"""Repair original evidence after process/acknowledgement loss without replay."""

from __future__ import annotations

import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.enterprise_cognition.outcomes import (
    OutcomeService,
    reconcile_pending_outcomes,
    recover_terminal_outcome,
)
from tests.test_application.test_enterprise_outcomes import NOW, snapshot
from tests.test_application.test_enterprise_outcomes import runtime as runtime

KEY = "enterprise_outcome_recovery"


def observe(runtime):
    def read(run_id, *, repository):
        return OutcomeService(
            repository=repository,
            projection=runtime.projection,
            memory_service=runtime.service.memory_service,
            clock=lambda: NOW,
        ).evaluate(run_id, tenant_id="2", actor_id="7", mod_id="sales")

    return read


def recover(runtime, *, now=1000, observer=None, repository=None):
    return reconcile_pending_outcomes(
        repository=repository or runtime.repo,
        observer=observer or observe(runtime),
        now=now,
    )


def test_restart_discovers_completed_original_run_before_any_hook(runtime):
    runtime.repo.save(runtime.run)
    original = runtime.repo.get(runtime.run.run_id)
    restarted = SQLAlchemyAgentRunRepository(session_factory=runtime.sessions)

    assert recover(runtime, repository=restarted) == 1
    assert recover(runtime, now=2000, repository=restarted) == 0
    saved = restarted.get(runtime.run.run_id)
    assert saved.status == original.status == "completed"
    assert saved.steps == original.steps and saved.tool_calls == original.tool_calls
    assert saved.metadata["approval_receipt"] == original.metadata["approval_receipt"]
    assert saved.metadata[KEY]["status"] == "recorded"
    assert saved.metadata[KEY]["memory_status"] == "pending"
    assert len(runtime.calls) == 1
    assert len(runtime.memory.list_memories(runtime.owner)) == 1
    assert len([e for e in saved.events if e.event_type == "enterprise.outcome_recorded"]) == 1


def test_sql_due_filter_precedes_limit_and_skips_unrelated_or_malformed_rows(runtime):
    runtime.repo.save(runtime.run)
    for index in range(25):
        ordinary = AgentRun(user_id="7", message=f"unbound-{index}", status="completed")
        runtime.repo.save(ordinary)
    from app.db.models.agent import AgentRunRecord

    with runtime.sessions.begin() as db:
        db.get(AgentRunRecord, ordinary.run_id).payload_json = "not valid JSON"
    delayed = copy.deepcopy(runtime.run)
    delayed.run_id = "delayed-outcome"
    delayed.metadata[KEY] = {"status": "pending", "next_attempt_at": 5000}
    runtime.repo.save(delayed)
    assert (
        reconcile_pending_outcomes(
            repository=runtime.repo, observer=observe(runtime), limit=1, now=1000
        )
        == 1
    )
    assert runtime.repo.get(runtime.run.run_id).metadata[KEY]["status"] == "recorded"
    assert runtime.repo.get(delayed.run_id).metadata[KEY]["status"] == "pending"


def test_process_death_after_claim_recovers_only_after_original_lease(runtime):
    runtime.repo.save(runtime.run)

    def die(*args, **kwargs):
        raise SystemExit("process stopped between claim and observation")

    with pytest.raises(SystemExit):
        recover(runtime, observer=die)
    assert runtime.repo.get(runtime.run.run_id).metadata[KEY]["status"] == "observing"
    restarted = SQLAlchemyAgentRunRepository(session_factory=runtime.sessions)
    assert recover(runtime, now=1119, repository=restarted) == 0
    assert recover(runtime, now=1121, repository=restarted) == 1
    assert runtime.repo.get(runtime.run.run_id).metadata[KEY]["attempt"] == 2
    assert len(runtime.calls) == 1


def test_memory_ack_loss_retries_first_frozen_measurement_without_new_action(runtime):
    runtime.repo.save(runtime.run)
    propose = runtime.memory.propose_memory_candidate
    fail = [True]

    def lose_ack(*args, **kwargs):
        result = propose(*args, **kwargs)
        if fail.pop() if fail else False:
            raise OSError("memory commit succeeded; acknowledgement lost")
        return result

    runtime.service.memory_service = SimpleNamespace(
        propose_memory_candidate=lose_ack,
        _store=runtime.memory._store,
        list_memories=runtime.memory.list_memories,
    )
    assert recover(runtime) == 1
    first = runtime.repo.get(runtime.run.run_id)
    assert first.metadata[KEY]["status"] == "pending"
    assert first.metadata[KEY]["memory_status"] == "retry_required"
    assert recover(runtime, now=1001) == 0
    runtime.state["after"] = snapshot(0, seconds=-1)
    assert recover(runtime, now=1011) == 1
    saved = runtime.repo.get(runtime.run.run_id)
    assert saved.metadata[KEY]["status"] == "recorded"
    assert saved.metadata[KEY]["observation_id"] == first.metadata[KEY]["observation_id"]
    assert saved.steps == first.steps and saved.tool_calls == first.tool_calls
    memories = runtime.memory.list_memories(runtime.owner)
    assert len(memories) == 1 and memories[0]["value"]["after"]["value"] == "2"


@pytest.mark.parametrize("lost_phase", ["observing", "recorded"])
def test_commit_ack_loss_uses_original_row_and_identity(runtime, monkeypatch, lost_phase):
    runtime.repo.save(runtime.run)
    save = runtime.repo.save_if_unchanged
    failed = []

    def lose_ack(run, previous):
        result = save(run, previous)
        if result and not failed and run.metadata.get(KEY, {}).get("status") == lost_phase:
            failed.append(True)
            raise OSError("database acknowledgement lost after commit")
        return result

    monkeypatch.setattr(runtime.repo, "save_if_unchanged", lose_ack)
    recover(runtime)
    recover(runtime, now=1121)
    saved = runtime.repo.get(runtime.run.run_id)
    assert saved.metadata[KEY]["status"] == "recorded"
    assert len(runtime.memory.list_memories(runtime.owner)) == 1
    assert len([e for e in saved.events if e.event_type == "enterprise.outcome_observed"]) == 1
    assert saved.tool_calls == runtime.run.tool_calls


def test_concurrent_sql_claims_have_one_observer(runtime, monkeypatch):
    runtime.repo.save(runtime.run)
    barrier = threading.Barrier(2)
    save = runtime.repo.save_if_unchanged

    def race(run, previous):
        if run.metadata.get(KEY, {}).get("status") == "observing" and KEY not in previous.metadata:
            barrier.wait(timeout=5)
        return save(run, previous)

    monkeypatch.setattr(runtime.repo, "save_if_unchanged", race)
    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = [pool.submit(recover, runtime) for _ in range(2)]
        assert sorted(attempt.result(timeout=10) for attempt in attempts) == [0, 1]
    assert len(runtime.calls) == 1
    assert len(runtime.memory.list_memories(runtime.owner)) == 1


def test_expired_authorization_stays_pending_without_read_or_effect(runtime):
    runtime.repo.save(runtime.run)
    result = recover_terminal_outcome(runtime.run.run_id, repository=runtime.repo, now=1000)
    assert result["reason_code"] == "observation_authorization_unavailable"
    saved = runtime.repo.get(runtime.run.run_id)
    assert saved.metadata[KEY]["status"] == "pending"
    assert saved.tool_calls == runtime.run.tool_calls
    assert runtime.calls == [] and runtime.memory.list_memories(runtime.owner) == []


def test_chat_projection_failure_keeps_original_memory_for_retry(runtime):
    runtime.repo.save(runtime.run)
    read = observe(runtime)
    attempts = []

    def retry_chat(*args, **kwargs):
        result = read(*args, **kwargs)
        result["chat_projection_status"] = "retry_required" if not attempts else "recorded"
        attempts.append(result["memory_id"])
        return result

    assert recover(runtime, observer=retry_chat) == 1
    assert runtime.repo.get(runtime.run.run_id).metadata[KEY]["status"] == "pending"
    assert recover(runtime, observer=retry_chat, now=1011) == 1
    assert runtime.repo.get(runtime.run.run_id).metadata[KEY]["status"] == "recorded"
    assert attempts[0] == attempts[1]
    assert len(runtime.memory.list_memories(runtime.owner)) == 1


def test_stop_does_not_claim_or_observe_pending_rows(runtime):
    runtime.repo.save(runtime.run)
    assert (
        reconcile_pending_outcomes(
            repository=runtime.repo, observer=observe(runtime), stopped=lambda: True, now=1000
        )
        == 0
    )
    assert KEY not in runtime.repo.get(runtime.run.run_id).metadata
    assert runtime.calls == []


def test_dispatcher_startup_recovers_evidence_without_blocking_queue(runtime, monkeypatch):
    from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher
    from app.application.agent_orchestrator.task_execution_repository import (
        InMemoryTaskExecutionRepository,
    )

    runtime.repo.save(runtime.run)
    observer_started, release, queue_polled = (threading.Event() for _ in range(3))
    read = observe(runtime)

    def slow_observer(*args, **kwargs):
        observer_started.set()
        assert release.wait(timeout=5)
        return read(*args, **kwargs)

    class Queue(InMemoryTaskExecutionRepository):
        def claim(self, *args, **kwargs):
            queue_polled.set()
            return super().claim(*args, **kwargs)

    monkeypatch.setattr(
        "app.application.enterprise_cognition.outcomes.observe_terminal_run", slow_observer
    )
    dispatcher = AgentTaskDispatcher(
        run_repository=runtime.repo, execution_repository=Queue(), poll_seconds=0.02
    )
    dispatcher.start()
    try:
        assert observer_started.wait(timeout=3)
        assert queue_polled.wait(timeout=1)
    finally:
        release.set()
        dispatcher.stop(timeout=5)
    assert runtime.repo.get(runtime.run.run_id).metadata[KEY]["status"] == "recorded"
    assert len(runtime.memory.list_memories(runtime.owner)) == 1
