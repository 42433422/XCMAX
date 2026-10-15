"""Transaction boundaries for durable approval, run and dispatch storage."""

import multiprocessing
import os

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


def _approve_and_exit(url, run_id, token, before_commit):
    from app.application.agent_orchestrator.approval_transaction import approve_and_enqueue

    engine = create_engine(url)
    factory = sessionmaker(bind=engine)
    runs = SQLAlchemyAgentRunRepository(session_factory=factory, auto_create=False)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=factory, auto_create=False)
    if before_commit:
        enqueue = queue.enqueue_in_session

        def crash_after_flush(db, run, **kwargs):
            enqueue(db, run, **kwargs)
            db.flush()
            os._exit(71)  # No context-manager rollback or Python cleanup.

        queue.enqueue_in_session = crash_after_flush
    approve_and_enqueue(
        runs, queue, run_id=run_id, token=token, principal_id="owner", runtime_context={}
    )
    os._exit(72)  # Committed, but no response or dispatcher notification.


@pytest.mark.parametrize("before_commit", [True, False])
def test_process_death_preserves_atomic_approval_and_pollable_dispatch(
    tmp_path, monkeypatch, before_commit
):
    from app.application.agent_orchestrator.approval_grant import (
        ApprovalGrantError,
        issue_approval_grant,
    )
    from app.application.agent_orchestrator.approval_transaction import approve_and_enqueue
    from app.application.agent_orchestrator.run_models import AgentStep

    monkeypatch.setenv("SECRET_KEY", "crash-approval-test-" * 4)
    url = f"sqlite:///{tmp_path / 'crash.db'}"
    engine = create_engine(url)
    factory = sessionmaker(bind=engine)
    runs = SQLAlchemyAgentRunRepository(session_factory=factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
    run = AgentRun(
        user_id="owner",
        message="approve",
        status="waiting_user",
        steps=[
            AgentStep(node_id="node", tool_id="sales", action="create_order", status="waiting_user")
        ],
    )
    runs.save(run)
    queue.get(run.run_id)
    AgentApprovalConsumption.__table__.create(engine)
    token = issue_approval_grant(run, principal_id="owner")["grant"]
    engine.dispose()
    process = multiprocessing.get_context("spawn").Process(
        target=_approve_and_exit, args=(url, run.run_id, token, before_commit)
    )
    try:
        process.start()
        process.join(timeout=20)
        assert process.exitcode == (71 if before_commit else 72)
        with factory() as db:
            assert db.query(AgentApprovalConsumption).count() == (0 if before_commit else 1)
        if before_commit:
            assert runs.get(run.run_id).status == "waiting_user"
            assert queue.get(run.run_id) is None
            approve_and_enqueue(
                runs,
                queue,
                run_id=run.run_id,
                token=token,
                principal_id="owner",
                runtime_context={},
            )
        else:
            with pytest.raises(ApprovalGrantError):
                approve_and_enqueue(
                    runs,
                    queue,
                    run_id=run.run_id,
                    token=token,
                    principal_id="owner",
                    runtime_context={},
                )
        assert runs.get(run.run_id).status == "queued"
        with factory() as db:
            assert db.query(AgentApprovalConsumption).count() == 1
        # A replacement worker polls durable storage without a notification.
        claimed = queue.claim("replacement-worker", lease_seconds=30)
        assert claimed is not None and claimed.run_id == run.run_id
        assert claimed.execution_count == 1
        assert queue.claim("second-worker", lease_seconds=30) is None
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        engine.dispose()


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
