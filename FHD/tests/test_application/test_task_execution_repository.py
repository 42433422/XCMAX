from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.task_execution_repository import (
    SQLAlchemyTaskExecutionRepository,
)


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
    assert claimed.state == "claimed"
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
    assert completed.state == "completed"
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
    assert repository.get(run.run_id).state == "claimed"
    replacement = repository.claim("new", lease_seconds=60)
    assert replacement and replacement.lease_owner == "new"
    assert repository.finish(run.run_id, "old", "failed") is None
    assert repository.get(run.run_id).lease_owner == "new"
    assert repository.finish(run.run_id, "new", "completed").state == "completed"
    engine.dispose()
