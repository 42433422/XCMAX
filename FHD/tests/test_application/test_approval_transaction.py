"""Transaction boundaries for durable approval, run and dispatch storage."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.run_models import AgentRun, utc_now_iso
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.db.models.agent import AgentTaskRecord
from app.db.models.agent_approval import AgentApprovalConsumption


@pytest.mark.parametrize("failure_after", ["approval", "run", "queue", None])
def test_approval_run_and_queue_share_commit_boundary(tmp_path, failure_after):
    engine = create_engine(f"sqlite:///{tmp_path / 'transaction.db'}")
    factory = sessionmaker(bind=engine)
    runs = SQLAlchemyAgentRunRepository(session_factory=factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
    run = AgentRun(user_id="owner", message="approve", status="waiting_user")
    runs.save(run)
    queue.get(run.run_id)  # Initialize schema before the transaction.
    AgentApprovalConsumption.__table__.create(engine)

    def fail_at(stage):
        if failure_after == stage:
            raise RuntimeError("simulated interruption")

    def write_transaction():
        with factory.begin() as db:
            db.add(
                AgentApprovalConsumption(
                    jti="approval", run_id=run.run_id, step_id="step", consumed_at=utc_now_iso()
                )
            )
            db.flush()
            fail_at("approval")
            run.status = "queued"
            runs.save_in_session(db, run)
            db.flush()
            fail_at("run")
            queue.enqueue_in_session(db, run, requested_by="owner")
            db.flush()
            # A separate connection cannot observe a partially staged dispatch.
            assert queue.get(run.run_id) is None
            assert runs.get(run.run_id).status == "waiting_user"
            fail_at("queue")

    try:
        if failure_after:
            with pytest.raises(RuntimeError, match="simulated interruption"):
                write_transaction()
        else:
            write_transaction()
        # All readback uses fresh sessions after commit/rollback.
        assert runs.get(run.run_id).status == ("waiting_user" if failure_after else "queued")
        with factory() as db:
            assert db.query(AgentApprovalConsumption).count() == (0 if failure_after else 1)
            task = db.query(AgentTaskRecord).one()
            assert task.status == ("waiting_user" if failure_after else "queued")
        if failure_after:
            assert queue.claim("worker", lease_seconds=30) is None
        else:
            claimed = queue.claim("worker", lease_seconds=30)
            assert claimed is not None and claimed.run_id == run.run_id
    finally:
        engine.dispose()
