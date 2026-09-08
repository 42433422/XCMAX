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
        with pytest.raises(WorkerLeaseLost, match="another run"):
            fresh.save(AgentRun(user_id="owner", message="unrelated"))
        assert len(runs.list_recent()) == 1
    finally:
        engine.dispose()
