"""WG10: actual process death, concurrent takeover and SQLite write contention.

These are production SQL queue/claim/checkpoint regressions, not live model or
business acceptance. Existing native-task and tool-idempotency suites exercise
the executor and committed external effects across a crash.
"""

from __future__ import annotations

import random
import sqlite3
import threading
import time
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.worker_repository import (
    ClaimedRunRepository,
    WorkerLeaseLost,
)


def _repositories(url, *, auto_create=False, timeout=5.0):
    engine = create_engine(url, connect_args={"timeout": timeout})
    factory = sessionmaker(bind=engine)
    runs = SQLAlchemyAgentRunRepository(session_factory=factory, auto_create=auto_create)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=factory, auto_create=auto_create)
    return engine, runs, queue


def _checkpoint_worker(url, run_id, pipe):
    engine, runs, queue = _repositories(url)
    try:
        claim = queue.claim("departed", lease_seconds=300, run_id=run_id)
        assert claim is not None
        bound = ClaimedRunRepository(runs, claim, "departed")
        run = runs.get(run_id)
        for index, step in enumerate(run.steps):
            step.status = "completed"
            step.output = {"success": True, "data": [index]}
            bound.save(run)
            pipe.send(index)
            assert pipe.recv() == "next"
    finally:
        pipe.close()
        engine.dispose()


def _takeover_worker(url, run_id, owner, now, barrier, pipe):
    engine, _runs, queue = _repositories(url)
    try:
        barrier.wait(timeout=20)
        claim = queue.claim(owner, lease_seconds=300, run_id=run_id, now=now)
        pipe.send(None if claim is None else claim.lease_owner)
    finally:
        pipe.close()
        engine.dispose()


def _stop(process, pipe):
    if process.is_alive():
        process.kill()
    process.join(timeout=5)
    assert not process.is_alive(), "fault-injection child did not terminate"
    pipe.close()
    process.close()


@pytest.mark.parametrize("seed", [1, 5, 9])
def test_random_checkpoint_kill_preserves_progress_and_has_one_takeover(
    tmp_path, spawn_context, seed
):
    url = f"sqlite:///{tmp_path / 'worker.db'}"
    engine, runs, queue = _repositories(url, auto_create=True)
    run = AgentRun(user_id="owner", message="checkpoint preservation", status="running")
    run.steps = [
        AgentStep(node_id=str(index), tool_id="business_db", action="read", idempotent=True)
        for index in range(5)
    ]
    runs.save(run)
    queue.enqueue(run, idempotency_key="original-request", fingerprint="original-body")
    kill_after = random.Random(seed).randrange(len(run.steps))
    received, sending = spawn_context.Pipe()
    process = spawn_context.Process(target=_checkpoint_worker, args=(url, run.run_id, sending))
    process.start()
    sending.close()
    workers = []
    try:
        for index in range(kill_after + 1):
            assert received.poll(20), f"seed {seed}: checkpoint {index} was not persisted"
            assert received.recv() == index
            if index < kill_after:
                received.send("next")
        # Abrupt OS termination cannot run worker finally blocks or release its lease.
        process.kill()
        process.join(timeout=5)
        assert process.exitcode is not None and process.exitcode != 0
        original = queue.get(run.run_id)
        assert original.lease_owner == "departed" and original.execution_count == 1
        engine.dispose()
        engine, runs, queue = _repositories(url)
        saved = runs.get(run.run_id)
        assert [step.status for step in saved.steps] == (
            ["completed"] * (kill_after + 1) + ["pending"] * (4 - kill_after)
        )
        assert [step.output for step in saved.steps[: kill_after + 1]] == [
            {"success": True, "data": [index]} for index in range(kill_after + 1)
        ]
        # Advance only the queue's injected clock; there is no shortened real lease.
        expired = (
            datetime.fromisoformat(original.lease_expires_at) + timedelta(seconds=1)
        ).isoformat()
        barrier = spawn_context.Barrier(4)
        for index in range(4):
            receiver, sender = spawn_context.Pipe(duplex=False)
            child = spawn_context.Process(
                target=_takeover_worker,
                args=(url, run.run_id, f"replacement-{index}", expired, barrier, sender),
            )
            child.start()
            sender.close()
            workers.append((child, receiver))
        outcomes = []
        for child, receiver in workers:
            assert receiver.poll(20), f"seed {seed}: recovery worker did not return"
            outcomes.append(receiver.recv())
            child.join(timeout=5)
            assert child.exitcode == 0
        assert sum(owner is not None for owner in outcomes) == 1
        recovered = queue.get(run.run_id)
        assert (recovered.execution_count, recovered.recovery_count) == (2, 1)
        assert recovered.lease_owner == next(owner for owner in outcomes if owner)
        assert runs.get(run.run_id).to_dict() == saved.to_dict()
        journal = queue.lifecycle(run.run_id)
        assert (
            queue.finish(
                run.run_id, "departed", "completed", execution_count=original.execution_count
            )
            is None
        )
        assert not queue.mark_open_effect(
            run.run_id,
            "departed-write",
            owner_id="departed",
            execution_count=original.execution_count,
        )
        assert queue.get(run.run_id) == recovered
        assert queue.lifecycle(run.run_id) == journal
        with pytest.raises(WorkerLeaseLost):
            ClaimedRunRepository(runs, original, "departed").save(saved)
        assert runs.get(run.run_id).to_dict() == saved.to_dict()
    finally:
        _stop(process, received)
        for child, receiver in workers:
            _stop(child, receiver)
        engine.dispose()


def test_sqlite_write_lock_retries_in_dispatcher_without_losing_task(tmp_path):
    from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher

    url = f"sqlite:///{tmp_path / 'locked-queue.db'}"
    engine, runs, queue = _repositories(url, auto_create=True, timeout=0.1)
    # The control result is already durable. The dispatcher must catch its queue
    # up after the outage, without launching a model/tool or undoing cancellation.
    run = AgentRun(user_id="owner", message="cancelled before queue receipt", status="cancelled")
    runs.save(run)
    queue.enqueue(run)
    busy = threading.Event()

    @event.listens_for(engine, "handle_error")
    def observe_real_sqlite_busy(context):
        code = getattr(context.original_exception, "sqlite_errorcode", 0)
        if code & 0xFF == sqlite3.SQLITE_BUSY:
            busy.set()

    dispatcher = AgentTaskDispatcher(
        execution_repository=queue, run_repository=runs, max_workers=1, poll_seconds=0.02
    )
    holder = engine.raw_connection()
    try:
        holder.execute("BEGIN IMMEDIATE")
        dispatcher.start()
        assert busy.wait(10), "worker never observed the actual SQLite writer lock"
        assert dispatcher.snapshot()["running"] is True
        assert queue.get(run.run_id).state == "queued"
        assert queue.get(run.run_id).execution_count == 0
        holder.rollback()
        deadline = time.monotonic() + 10
        while queue.get(run.run_id).state != "cancelled" and time.monotonic() < deadline:
            time.sleep(0.02)
        assert queue.get(run.run_id).state == "cancelled"
        assert queue.get(run.run_id).execution_count == 1
        assert runs.get(run.run_id).status == "cancelled"
        assert dispatcher.snapshot()["running"] is True
    finally:
        holder.rollback()
        holder.close()
        dispatcher.stop(timeout=5)
        event.remove(engine, "handle_error", observe_real_sqlite_busy)
        engine.dispose()
