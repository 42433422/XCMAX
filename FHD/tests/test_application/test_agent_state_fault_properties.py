"""WG10 J07/J08: generated lifecycle sequences and delayed SQL result delivery.

The queue, control CAS, lifecycle journal and reconnects are production code.
Hypothesis generates operation order; it does not replace the runtime or DB.
"""

from __future__ import annotations

import copy
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

import pytest
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.run_lifecycle import RunLifecycleMixin
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_execution_repository import (
    SQLAlchemyTaskExecutionRepository,
)

_FINAL = {"succeeded", "failed", "timed_out", "cancelled", "rejected", "unknown"}


class DurableLifecycleFaultMachine(RuleBasedStateMachine):
    """Generate control, receipt, restart and replay orders on a file-backed DB."""

    def __init__(self):
        super().__init__()
        self.directory = tempfile.TemporaryDirectory(prefix="wg10-states-")
        self.url = f"sqlite:///{Path(self.directory.name) / 'tasks.sqlite'}"
        self.frozen = {}
        self.serial = 0
        self.owner = "never-claimed"
        self._connect()
        self._new_task()

    def _connect(self):
        self.engine = create_engine(self.url)
        self.queue = SQLAlchemyTaskExecutionRepository(
            session_factory=sessionmaker(bind=self.engine), jitter_ratio=0.0
        )

    def _new_task(self):
        self.serial += 1
        self.run = AgentRun(
            run_id=f"state-task-{self.serial}", user_id="owner", message="preserve task progress"
        )
        self.run.metadata["runtime_context"] = {"tenant_id": "state-tenant"}
        self.queue.enqueue(self.run, idempotency_key=self.run.run_id, fingerprint="same-intent")

    def _snapshot(self):
        return asdict(self.queue.get(self.run.run_id)), self.queue.lifecycle(self.run.run_id)

    @precondition(lambda self: self.queue.get(self.run.run_id).state in _FINAL)
    @rule()
    def next_task(self):
        self._new_task()

    @rule()
    def claim(self):
        before = self.queue.get(self.run.run_id)
        candidate = f"worker-{before.execution_count + 1}"
        claimed = self.queue.claim(candidate, lease_seconds=300, run_id=self.run.run_id)
        if before.state == "queued":
            assert claimed is not None
            assert claimed.execution_count == before.execution_count + 1
            self.owner = candidate
        else:
            assert claimed is None

    @rule(state=st.sampled_from(["paused", "waiting_input", "waiting_auth", "cancelled", "queued"]))
    def control(self, state):
        before = self._snapshot()
        changed = self.queue.transition(self.run.run_id, state)
        if changed is None:
            assert self._snapshot() == before, "rejected control changed durable evidence"

    @rule(state=st.sampled_from(["completed", "failed", "unknown", "waiting_approval"]))
    def receive_result(self, state):
        before = self._snapshot()
        finished = self.queue.finish(
            self.run.run_id,
            self.owner,
            state,
            error_code="business_rule" if state == "failed" else "",
        )
        if finished is None:
            assert self._snapshot() == before, "rejected receipt changed durable evidence"
        if finished is not None and finished.state == "succeeded":
            assert before[0]["state"] == "running" and state == "completed"

    @rule()
    def open_effect(self):
        before = self._snapshot()
        accepted = self.queue.mark_open_effect(
            self.run.run_id, "write-awaiting-receipt", owner_id=self.owner
        )
        assert accepted is (before[0]["state"] == "running")
        if not accepted:
            assert self._snapshot() == before

    @rule()
    def stale_receipt(self):
        before = self._snapshot()
        assert self.queue.finish(self.run.run_id, "never-claimed", "completed") is None
        assert not self.queue.mark_open_effect(
            self.run.run_id, "late-write", owner_id="never-claimed"
        )
        assert self._snapshot() == before

    @rule()
    def replay_admission(self):
        replay = copy.deepcopy(self.run)
        replay.run_id += "-duplicate"
        existing = self.queue.enqueue(
            replay, idempotency_key=self.run.run_id, fingerprint="same-intent"
        )
        assert existing.run_id == self.run.run_id
        assert self.queue.get(replay.run_id) is None

    @rule(decision=st.sampled_from(["approve", "reject"]))
    def approval(self, decision):
        before = self._snapshot()
        changed = self.queue.resolve_approval(self.run.run_id, decision, "owner")
        if before[0]["state"] != "waiting_approval":
            assert changed is None
            assert self._snapshot() == before

    @rule(state=st.sampled_from(["", "complete-ish", "resume-anyway", "RUNNING?"]))
    def invalid_transition(self, state):
        before = self._snapshot()
        assert self.queue.transition(self.run.run_id, state) is None
        assert self._snapshot() == before

    @rule()
    def restart(self):
        before = self._snapshot()
        self.engine.dispose()
        self._connect()
        assert self._snapshot() == before

    @invariant()
    def control_and_uncertain_effects_survive_every_order(self):
        row, journal = self._snapshot()
        assert row["state"] in _FINAL | {
            "queued",
            "running",
            "paused",
            "blocked",
            "waiting_approval",
            "waiting_input",
            "waiting_auth",
        }
        if row["state"] == "running":
            assert row["lease_owner"] == self.owner and row["lease_expires_at"]
        else:
            assert not row["lease_owner"] and not row["lease_expires_at"]
        if journal["effects"]:
            assert row["state"] in {"running", "unknown"}
        if row["state"] == "unknown":
            assert not row["finished_at"]
        if row["state"] in _FINAL:
            self.frozen.setdefault(self.run.run_id, (row["state"], list(journal["effects"])))
        for run_id, (state, effects) in self.frozen.items():
            assert self.queue.get(run_id).state == state, "terminal/unknown task reopened"
            assert self.queue.lifecycle(run_id)["effects"] == effects, "unsettled evidence erased"

    def teardown(self):
        self.engine.dispose()
        self.directory.cleanup()


TestDurableLifecycleFaultMachine = DurableLifecycleFaultMachine.TestCase
TestDurableLifecycleFaultMachine.settings = settings(
    max_examples=30, stateful_step_count=40, derandomize=True, database=None, deadline=None
)


def _apply_control(repository, previous, action):
    command = repository.request_task_control(previous.run_id, action, requested_by="owner")
    controlled = copy.deepcopy(previous)
    RunLifecycleMixin._mark_controlled(
        controlled, action, requested_by="owner", command_id=command.command_id
    )
    if action == "pause":
        controlled.metadata["control"]["resume_status"] = "running"
    assert repository.save_control_if_unchanged(controlled, previous)
    repository.mark_task_control(command.command_id, "applied")
    return repository.get(previous.run_id), command


@pytest.mark.parametrize("late_status", ["running", "completed", "failed"])
@pytest.mark.parametrize("delivery", ["snapshot_cas", "whole_run_save"])
@pytest.mark.parametrize("prior_pause", [False, True])
def test_cancel_fences_late_result_after_sql_reconnect(
    tmp_path, late_status, delivery, prior_pause
):
    """Release a real waiting writer only after cancellation has committed."""
    url = f"sqlite:///{tmp_path / 'cancel-late.sqlite'}"
    controller_engine = create_engine(url)
    writer_engine = create_engine(url)
    controller = SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=controller_engine))
    writer = SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=writer_engine))
    original = controller.save(
        AgentRun(user_id="owner", message="delayed result", status="running")
    )
    if prior_pause:
        original, _ = _apply_control(controller, original, "pause")
    received, release = threading.Event(), threading.Event()

    def delayed_result():
        previous = writer.get(original.run_id)
        late = copy.deepcopy(previous)
        late.status = late_status
        late.final_output = {"late_result": True}
        received.set()
        assert release.wait(5), "cancellation never released delayed result"
        if delivery == "snapshot_cas":
            return writer.save_if_unchanged(late, previous)
        writer.save(late)
        return None

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(delayed_result)
            try:
                assert received.wait(5)
                previous = controller.get(original.run_id)
                cancelled, command = _apply_control(controller, previous, "cancel")
            finally:
                release.set()
            if delivery == "snapshot_cas":
                assert future.result(timeout=5) is False
            else:
                future.result(timeout=5)
        writer_engine.dispose()
        controller_engine.dispose()
        reader = SQLAlchemyAgentRunRepository(
            session_factory=sessionmaker(bind=controller_engine), auto_create=False
        )
        final = reader.get(original.run_id)
        assert final.status == "cancelled"
        assert final.final_output["cancelled"] is True
        assert final.metadata["control"] == cancelled.metadata["control"]
        assert reader.latest_task_control(original.run_id).command_id == command.command_id
        assert reader.latest_task_control(original.run_id).status == "applied"
        assert any(event.event_type == "run.cancelled" for event in final.events)
    finally:
        release.set()
        writer_engine.dispose()
        controller_engine.dispose()


@pytest.mark.parametrize("next_control", ["resume", "cancel"])
def test_nonterminal_pause_allows_fresh_control_generation(tmp_path, next_control):
    engine = create_engine(f"sqlite:///{tmp_path / 'control-evolution.sqlite'}")
    repository = SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=engine))
    try:
        original = repository.save(AgentRun(user_id="owner", message="control", status="running"))
        paused, pause_command = _apply_control(repository, original, "pause")
        if next_control == "cancel":
            latest, command = _apply_control(repository, paused, "cancel")
        else:
            command = repository.request_task_control(
                original.run_id, "resume", requested_by="owner"
            )
            resumed = copy.deepcopy(paused)
            resumed.status = "running"
            resumed.metadata["control"] = {
                "state": "running",
                "requested_by": "owner",
                "command_id": command.command_id,
            }
            assert repository.save_if_unchanged(resumed, paused)
            latest = repository.get(original.run_id)
        assert command.command_id != pause_command.command_id
        assert latest.metadata["control"]["command_id"] == command.command_id
        assert latest.status == ("cancelled" if next_control == "cancel" else "running")
    finally:
        engine.dispose()
