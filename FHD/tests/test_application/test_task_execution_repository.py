from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.task_execution_repository import (
    InMemoryTaskExecutionRepository,
    SQLAlchemyTaskExecutionRepository,
)


@pytest.fixture(params=["memory", "sql"])
def lifecycle_queue(request, tmp_path):
    if request.param == "memory":
        yield InMemoryTaskExecutionRepository(approval_timeout_seconds=1)
        return
    engine = create_engine(f"sqlite:///{tmp_path / 'lifecycle.db'}")
    repository = SQLAlchemyTaskExecutionRepository(
        session_factory=sessionmaker(bind=engine), approval_timeout_seconds=1
    )
    yield repository
    engine.dispose()


@pytest.mark.parametrize("state", ["paused", "blocked", "waiting_input", "waiting_auth"])
def test_nonapproval_wait_keeps_identity_and_never_expires_as_rejection(lifecycle_queue, state):
    repo = lifecycle_queue
    run = AgentRun(user_id="owner", message="original task", status="queued")
    repo.enqueue(run)
    claimed = repo.claim("worker", lease_seconds=30)
    assert claimed is not None
    waiting = repo.finish(run.run_id, "worker", state)
    assert waiting is not None and waiting.state == state
    assert not waiting.finished_at
    assert repo.resolve_approval(run.run_id, "approve", "owner") is None
    future = (datetime.fromisoformat(waiting.updated_at) + timedelta(days=2)).isoformat()
    assert repo.claim("another-worker", lease_seconds=30, now=future) is None
    assert repo.get(run.run_id).state == state
    assert not repo.lifecycle(run.run_id)["approval_requested_at"]


def test_lost_completion_is_unknown_and_cannot_be_approved_or_requeued(lifecycle_queue):
    repo = lifecycle_queue
    run = AgentRun(user_id="owner", message="write once", status="queued")
    repo.enqueue(run)
    assert repo.claim("worker", lease_seconds=30) is not None
    repo.mark_open_effect(run.run_id, "original-write")
    uncertain = repo.finish(run.run_id, "worker", "failed", error_code="timeout")
    assert uncertain is not None and uncertain.state == "unknown"
    assert uncertain.last_error_code == "needs_verification"
    assert not uncertain.finished_at
    assert repo.lifecycle(run.run_id)["effects"] == ["original-write"]
    assert repo.enqueue(run).state == "unknown"
    assert repo.resolve_approval(run.run_id, "approve", "owner") is None
    assert repo.transition(run.run_id, "completed") is None
    assert repo.claim("another-worker", lease_seconds=30) is None


def test_stale_worker_cannot_clear_effects_or_append_lifecycle_history(lifecycle_queue):
    repo = lifecycle_queue
    run = AgentRun(user_id="owner", message="late receipt", status="queued")
    repo.enqueue(run)
    assert repo.claim("current-worker", lease_seconds=30) is not None
    repo.mark_open_effect(run.run_id, "original-write")
    before = repo.lifecycle(run.run_id)
    assert repo.finish(run.run_id, "stale-worker", "completed") is None
    assert repo.lifecycle(run.run_id) == before
    assert repo.get(run.run_id).lease_owner == "current-worker"


def test_stale_worker_cannot_open_effect_or_poison_current_claim(lifecycle_queue):
    from app.application.agent_orchestrator import task_dispatcher
    from app.application.agent_orchestrator.worker_repository import WorkerLeaseLost

    repo = lifecycle_queue
    run = AgentRun(user_id="owner", message="late dispatch", status="queued")
    repo.enqueue(run)
    assert repo.claim("current-worker", lease_seconds=30) is not None
    before = repo.lifecycle(run.run_id)
    token = task_dispatcher._open_effect.set((repo, run.run_id, "stale-worker"))
    try:
        with pytest.raises(WorkerLeaseLost):
            task_dispatcher.note_open_effect(run.run_id, "must-not-write")
    finally:
        task_dispatcher._open_effect.reset(token)
    assert repo.lifecycle(run.run_id) == before
    assert repo.mark_open_effect(run.run_id, "owned-write", owner_id="current-worker") is True
    assert repo.lifecycle(run.run_id)["effects"] == ["owned-write"]


def test_sql_queue_claim_is_atomic_renewable_and_recoverable(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'task-execution.db'}")
    session_factory = sessionmaker(bind=engine)
    first = SQLAlchemyTaskExecutionRepository(session_factory=session_factory)
    second = SQLAlchemyTaskExecutionRepository(session_factory=session_factory)
    run = AgentRun(user_id="owner", message="并发任务", status="queued")
    run.metadata["runtime_context"] = {"tenant_id": "tenant-a"}
    run.metadata["task_context"] = {"task_id": "task-atomic"}

    queued = first.enqueue(run, requested_by="owner", priority=10)
    assert set(second.list_for_run_ids([run.run_id, "missing"])) == {run.run_id}
    claim_time = datetime.fromisoformat(queued.available_at.replace("Z", "+00:00"))
    claimed = first.claim("worker-1", lease_seconds=10, now=claim_time.isoformat())

    assert claimed is not None
    assert claimed.state == "running"
    assert claimed.lease_owner == "worker-1"
    assert claimed.execution_count == 1
    assert second.claim("worker-2", lease_seconds=10, now=claim_time.isoformat()) is None
    assert second.heartbeat(run.run_id, "wrong-worker", lease_seconds=10) is False
    assert first.heartbeat(run.run_id, "worker-1", lease_seconds=10) is True
    assert second.finish(run.run_id, "wrong-worker", "completed") is None

    recovered = second.claim(
        "worker-2",
        lease_seconds=10,
        now=(claim_time + timedelta(seconds=30)).isoformat(),
    )
    assert recovered is not None
    assert recovered.lease_owner == "worker-2"
    assert recovered.execution_count == 2
    assert recovered.recovery_count == 1

    completed = first.finish(run.run_id, "worker-2", "completed")
    assert completed is not None
    assert completed.state == "succeeded"
    assert completed.tenant_id == "tenant-a"
    assert completed.task_id == "task-atomic"
    assert completed.finished_at


def _claim_in_process(url, owner, ready, start, results):
    engine = create_engine(url)
    repository = SQLAlchemyTaskExecutionRepository(
        session_factory=sessionmaker(bind=engine), auto_create=False
    )
    ready.put(owner)
    if not start.wait(15):
        raise RuntimeError("claim barrier timed out")
    claimed = repository.claim(owner, lease_seconds=60)
    results.put(claimed.lease_owner if claimed else None)
    engine.dispose()


def test_independent_processes_cannot_claim_the_same_run(tmp_path):
    import multiprocessing

    url = f"sqlite:///{tmp_path / 'process-queue.db'}"
    engine = create_engine(url)
    repository = SQLAlchemyTaskExecutionRepository(session_factory=sessionmaker(bind=engine))
    run = AgentRun(user_id="owner", message="race", status="queued")
    repository.enqueue(run)
    ctx = multiprocessing.get_context("spawn")
    ready, results = ctx.Queue(), ctx.Queue()
    start = ctx.Event()
    processes = [
        ctx.Process(target=_claim_in_process, args=(url, owner, ready, start, results))
        for owner in ("one", "two")
    ]
    try:
        for process in processes:
            process.start()
        assert {ready.get(timeout=15), ready.get(timeout=15)} == {"one", "two"}
        start.set()
        claims = [results.get(timeout=15), results.get(timeout=15)]
        assert sum(claim is not None for claim in claims) == 1
        for process in processes:
            process.join(timeout=15)
            assert process.exitcode == 0
        assert repository.get(run.run_id).lease_owner == next(claim for claim in claims if claim)
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        engine.dispose()


def test_expired_owner_cannot_renew_or_finish_before_replacement(tmp_path, monkeypatch):
    from app.application.agent_orchestrator import task_execution_sql_repository as sql_repo

    engine = create_engine(f"sqlite:///{tmp_path / 'expired.db'}")
    repository = SQLAlchemyTaskExecutionRepository(session_factory=sessionmaker(bind=engine))
    run = AgentRun(user_id="owner", message="expired", status="queued")
    queued = repository.enqueue(run)
    now = datetime.fromisoformat(queued.available_at.replace("Z", "+00:00"))
    claimed = repository.claim("old", lease_seconds=10, now=now.isoformat())
    assert claimed is not None
    expired = (now + timedelta(seconds=10)).isoformat()
    monkeypatch.setattr(sql_repo, "utc_now_iso", lambda: expired)
    assert not repository.heartbeat(run.run_id, "old", lease_seconds=60)
    assert repository.finish(run.run_id, "old", "completed") is None
    assert repository.get(run.run_id).state == "running"
    replacement = repository.claim("new", lease_seconds=60)
    assert replacement and replacement.lease_owner == "new"
    assert repository.finish(run.run_id, "old", "failed") is None
    assert repository.get(run.run_id).lease_owner == "new"
    assert repository.finish(run.run_id, "new", "completed").state == "succeeded"
    engine.dispose()


def test_repository_initialization_failure_never_silently_accepts_volatile_runs(monkeypatch):
    import pytest

    from app.application.agent_orchestrator import run_repository as runs
    from app.application.agent_orchestrator import task_execution_repository as queue

    monkeypatch.delenv("FHD_ENV", raising=False)
    monkeypatch.delenv("XCAGI_AGENT_RUN_REQUIRE_DURABLE", raising=False)
    monkeypatch.setattr(runs, "_agent_run_repository", None)
    monkeypatch.setattr(queue, "_task_execution_repository", None)

    class BrokenStore:
        def __init__(self):
            raise OSError("database unavailable")

    monkeypatch.setattr(runs, "SQLAlchemyAgentRunRepository", BrokenStore)
    monkeypatch.setattr(queue, "SQLAlchemyTaskExecutionRepository", BrokenStore)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="durable AgentRun"):
            runs.get_agent_run_repository()
        with pytest.raises(RuntimeError, match="durable task execution"):
            queue.get_task_execution_repository()
    assert runs._agent_run_repository is None
    assert queue._task_execution_repository is None


def test_reset_retires_disposed_queues_retained_by_failed_tests(monkeypatch):
    import weakref

    from sqlalchemy.pool import StaticPool

    from app.application.agent_orchestrator import task_execution_repository as queue

    monkeypatch.setattr(queue, "_task_execution_repository", None)
    monkeypatch.setattr(queue, "_OPEN_REPOSITORIES", weakref.WeakSet())
    engine = create_engine("sqlite://", poolclass=StaticPool)
    retired = SQLAlchemyTaskExecutionRepository(session_factory=sessionmaker(bind=engine))
    run = AgentRun(user_id="owner", message="retired database", status="queued")
    retired.enqueue(run)
    queue.set_task_execution_repository_for_tests(retired)
    assert queue.locate_task_execution(run.run_id)[0] is retired
    engine.dispose()

    # A failed test's traceback retains its repositories after fixture teardown.
    # Looking up a different task must not reconnect to that discarded in-memory DB.
    queue.set_task_execution_repository_for_tests(None)
    assert queue.locate_task_execution("next-test-task") == (None, None)
    current = queue.InMemoryTaskExecutionRepository()
    queue.set_task_execution_repository_for_tests(current)
    current.enqueue(run)
    assert queue.locate_task_execution(run.run_id)[0] is current


def test_memory_mode_is_explicit_development_only_and_shared_by_run_and_queue(monkeypatch):
    import pytest

    from app.application.agent_orchestrator import run_repository as runs
    from app.application.agent_orchestrator import task_execution_repository as queue

    monkeypatch.setenv("XCAGI_AGENT_RUN_REQUIRE_DURABLE", "false")

    class UnexpectedSQL:
        def __init__(self):
            raise OSError("offline development mode")

    monkeypatch.setattr(runs, "SQLAlchemyAgentRunRepository", UnexpectedSQL)
    monkeypatch.setattr(queue, "SQLAlchemyTaskExecutionRepository", UnexpectedSQL)
    for environment in ("", "production", "prod", "staging", "development", "dev", "test"):
        monkeypatch.setenv("FHD_ENV", environment)
        monkeypatch.setattr(runs, "_agent_run_repository", None)
        monkeypatch.setattr(queue, "_task_execution_repository", None)
        monkeypatch.setattr(runs, "_agent_run_repository_status", {})
        if environment not in {"development", "dev", "test"}:
            with pytest.raises(RuntimeError):
                runs.get_agent_run_repository()
            with pytest.raises(RuntimeError):
                queue.get_task_execution_repository()
            continue
        assert isinstance(runs.get_agent_run_repository(), runs.InMemoryAgentRunRepository)
        assert isinstance(
            queue.get_task_execution_repository(), queue.InMemoryTaskExecutionRepository
        )
        assert (
            runs.get_agent_run_repository_status()["degraded_reason"] == "explicit development mode"
        )
