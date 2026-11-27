import multiprocessing
import threading
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.worker_repository import (
    ClaimedRunRepository,
    WorkerLeaseLost,
)
from app.db.models.agent import AgentTaskExecutionRecord


def test_late_worker_cleanup_keeps_replacement_heartbeat(tmp_path, monkeypatch):
    from app.application.agent_orchestrator import task_dispatcher

    engine = create_engine(f"sqlite:///{tmp_path / 'dispatcher-takeover.db'}")
    factory = sessionmaker(bind=engine)
    runs = SQLAlchemyAgentRunRepository(session_factory=factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
    run = AgentRun(user_id="owner", message="overlapping worker generations")
    runs.save(run)
    queue.enqueue(run)
    entered = [threading.Event(), threading.Event()]
    release = [threading.Event(), threading.Event()]

    def orchestrator(repository):
        generation = repository._execution.execution_count - 1

        def execute(run_id, **_kwargs):
            entered[generation].set()
            assert release[generation].wait(10)
            result = repository.get(run_id)
            result.status = "paused"
            repository.save(result)
            return result

        return SimpleNamespace(execute_dispatched_run=execute)

    dispatcher = task_dispatcher.AgentTaskDispatcher(
        run_repository=runs,
        execution_repository=queue,
        max_workers=2,
        orchestrator_factory=orchestrator,
        lease_seconds=60,
        heartbeat_seconds=20,
    )
    monkeypatch.setattr(dispatcher, "_recover_outcomes", lambda: None)
    monkeypatch.setattr(
        task_dispatcher, "uuid", SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="same-owner"))
    )
    try:
        dispatcher._dispatch_available()
        assert entered[0].wait(5)
        first = dispatcher._active[run.run_id]
        with factory.begin() as db:
            db.query(AgentTaskExecutionRecord).filter_by(run_id=run.run_id).update(
                {"lease_expires_at": "2000-01-01T00:00:00+00:00"}
            )
        dispatcher._dispatch_available()
        assert entered[1].wait(5)
        second = dispatcher._active[run.run_id]
        assert first.owner_id == second.owner_id
        assert second.execution.execution_count == first.execution.execution_count + 1
        release[0].set()
        first.thread.join(5)
        assert not first.thread.is_alive()
        assert dispatcher._active[run.run_id] is second
        second.last_heartbeat = float("-inf")
        previous = queue.get(run.run_id).heartbeat_at
        dispatcher._prune_and_heartbeat()
        assert queue.get(run.run_id).heartbeat_at > previous
        assert queue.get(run.run_id).execution_count == second.execution.execution_count
        release[1].set()
        second.thread.join(5)
        assert not second.thread.is_alive()
        assert dispatcher.snapshot()["active_count"] == 0
        assert runs.get(run.run_id).status == queue.get(run.run_id).state == "paused"
    finally:
        for event in release:
            event.set()
        dispatcher.stop(timeout=2)
        engine.dispose()


def _delayed_worker_save(url, ready, resume, result):
    engine = create_engine(url)
    factory = sessionmaker(bind=engine)
    runs = SQLAlchemyAgentRunRepository(session_factory=factory, auto_create=False)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=factory, auto_create=False)
    try:
        execution = queue.claim("old-process", lease_seconds=60)
        assert execution is not None
        stale_run = runs.get(execution.run_id)
        ready.put(execution.run_id)
        if not resume.wait(20):
            raise RuntimeError("takeover barrier timed out")
        stale_run.status = "failed"
        try:
            ClaimedRunRepository(runs, execution, "old-process").save(stale_run)
        except WorkerLeaseLost:
            result.put("rejected")
        else:
            result.put("overwritten")
    finally:
        engine.dispose()


def test_stale_process_cannot_overwrite_replacement_state(tmp_path):
    url = f"sqlite:///{tmp_path / 'process-fencing.db'}"
    engine = create_engine(url)
    factory = sessionmaker(bind=engine)
    runs = SQLAlchemyAgentRunRepository(session_factory=factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
    run = AgentRun(user_id="owner", message="process takeover", status="queued")
    runs.save(run)
    queue.enqueue(run)
    ctx = multiprocessing.get_context("spawn")
    ready, result, resume = ctx.Queue(), ctx.Queue(), ctx.Event()
    process = ctx.Process(target=_delayed_worker_save, args=(url, ready, resume, result))
    try:
        process.start()
        assert ready.get(timeout=20) == run.run_id
        with factory.begin() as db:
            db.query(AgentTaskExecutionRecord).filter_by(run_id=run.run_id).update(
                {"lease_expires_at": "2000-01-01T00:00:00+00:00"}
            )
        replacement = queue.claim("replacement", lease_seconds=60)
        assert replacement is not None and replacement.recovery_count == 1
        run.status = "paused"
        ClaimedRunRepository(runs, replacement, "replacement").save(run)
        resume.set()
        assert result.get(timeout=20) == "rejected"
        process.join(timeout=20)
        assert process.exitcode == 0
        assert runs.get(run.run_id).status == "paused"
        assert queue.get(run.run_id).lease_owner == "replacement"
    finally:
        resume.set()
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        ready.close()
        result.close()
        engine.dispose()


def test_expired_and_replaced_workers_cannot_overwrite_run(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fencing.db'}")
    factory = sessionmaker(bind=engine)
    runs = SQLAlchemyAgentRunRepository(session_factory=factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
    run = AgentRun(user_id="owner", message="work", status="queued")
    runs.save(run)
    queue.enqueue(run)
    first = queue.claim("same-owner", lease_seconds=60)
    old = ClaimedRunRepository(runs, first, "same-owner")
    try:
        run.status = "running"
        old.save(run)
        with factory.begin() as db:
            db.query(AgentTaskExecutionRecord).filter_by(run_id=run.run_id).update(
                {"lease_expires_at": "2000-01-01T00:00:00+00:00"}
            )
        run.status = "failed"
        with pytest.raises(WorkerLeaseLost):
            old.save(run)
        assert runs.get(run.run_id).status == "running"
        # Even reusing an owner string cannot grant the previous execution access.
        replacement = queue.claim("same-owner", lease_seconds=60)
        assert replacement.execution_count == first.execution_count + 1
        fresh = ClaimedRunRepository(runs, replacement, "same-owner")
        newest = runs.get(run.run_id)
        newest.status = "paused"
        fresh.save(newest)
        with pytest.raises(WorkerLeaseLost):
            old.save(run)
        assert runs.get(run.run_id).status == "paused"
        with pytest.raises(WorkerLeaseLost):
            old.save_if_unchanged(run, newest)
        with pytest.raises(WorkerLeaseLost, match="another run"):
            fresh.save(AgentRun(user_id="owner", message="unrelated"))
        assert len(runs.list_recent()) == 1
    finally:
        engine.dispose()
