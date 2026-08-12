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
