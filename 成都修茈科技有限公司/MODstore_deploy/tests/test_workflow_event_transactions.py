"""Recovery uses a fresh transaction and never replays a workflow or a terminal."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from modstore_server import models, workflow_engine, workflow_event_runner
from modstore_server import workflow_execution_feedback as feedback
from tests import test_retort_workflow_execution as execution_tests
from tests import test_workflow_terminal_contract as terminal_tests
from tests.test_retort_experiment_lifecycle import start
from tests.test_retort_workflow_experiment import observations

experiment_run = execution_tests.experiment_run
workflow_experiment = execution_tests.workflow_experiment
execution_experiment = execution_tests.execution_experiment
workflow_database = terminal_tests.workflow_database


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["before_start_commit", "real_sandbox"])
async def test_flush_failure_rolls_back_before_recording_the_original_terminal(
    execution_experiment, monkeypatch, stage
):
    run = execution_experiment
    start(run)
    user_id = run["arms"]["1"]
    workflow_id = run["workflows"][user_id]
    await run["generate"](user_id)
    original_begin = feedback.begin_execution_feedback
    attempts, errors = [], []

    def poison(db):
        receipt = db.query(models.WorkflowExecution).filter_by(workflow_id=workflow_id).one()
        attempts.append(int(receipt.id))
        # A real constraint violation leaves even SQLite's ORM Session in the
        # failed-flush state that requires an explicit rollback.
        db.add(models.User(id=user_id, username=uuid4().hex, password_hash="synthetic"))
        try:
            db.flush()
        except IntegrityError as exc:
            exc.evidence = {"failed_operation": "synthetic_database_write"}
            errors.append(exc)
            raise

    if stage == "before_start_commit":

        def begin(db, execution):
            original_begin(db, execution)
            poison(db)

        monkeypatch.setattr(feedback, "begin_execution_feedback", begin)
        monkeypatch.setattr(
            workflow_engine.workflow_engine,
            "run_sandbox",
            lambda *_args, **_kwargs: pytest.fail("uncommitted admission cannot execute"),
        )
    else:
        monkeypatch.setattr(
            workflow_engine.workflow_engine,
            "run_sandbox",
            lambda db, *_args, **_kwargs: poison(db),
        )

    with pytest.raises(IntegrityError) as caught:
        run["sandbox"](user_id, {"private_input": "synthetic original task"})
    assert caught.value is errors[0]
    assert len(attempts) == 1
    with models.get_session_factory()() as db:
        receipts = db.query(models.WorkflowExecution).filter_by(workflow_id=workflow_id).all()
        starts = (
            db.query(models.OutboxEvent)
            .filter_by(event_id=f"{feedback.START_EVENT}:{attempts[0]}")
            .all()
        )
        if stage == "before_start_commit":
            assert receipts == starts == []
            assert observations(run) == observations(run, "experiment.exposed") == []
        else:
            assert len(receipts) == len(starts) == 1
            receipt = receipts[0]
            assert receipt.status == "failed" and receipt.completed_at is not None
            assert receipt.error_message == str(errors[0])
            assert json.loads(receipt.output_data) == errors[0].evidence
            assert json.loads(receipt.input_data) == {"private_input": "synthetic original task"}
            measured = observations(run)
            assert len(measured) == len(observations(run, "experiment.exposed")) == 1
            assert measured[0]["execution_id"] == receipt.id
            assert measured[0]["success"] is False
            feedback.complete_execution_feedback(db, receipt)
            db.commit()
            assert len(observations(run)) == 1


def _workflow(sf):
    with sf() as db:
        workflow = models.Workflow(user_id=1, name="transaction recovery", is_active=True)
        db.add(workflow)
        db.flush()
        workflow_id = int(workflow.id)
        db.commit()
        return workflow_id


def _run_sandbox(workflow_id):
    return workflow_engine.run_workflow_sandbox(
        workflow_id, {"synthetic": True}, mock_employees=False, user_id=1
    )


@pytest.mark.parametrize("committed", [False, True])
def test_start_commit_error_reads_the_durable_identity_without_replaying(
    workflow_database, monkeypatch, committed
):
    sf = workflow_database
    workflow_id = _workflow(sf)
    monkeypatch.setattr(workflow_event_runner, "get_session_factory", lambda: sf)
    original_commit = sf.class_.commit
    error = OperationalError("COMMIT", {}, RuntimeError("synthetic acknowledgement lost"))
    attempts = []

    def commit(db):
        row = next(
            (
                item
                for item in db.identity_map.values()
                if isinstance(item, models.WorkflowExecution)
            ),
            None,
        )
        if row is not None and not attempts:
            attempts.append(int(row.id))
            if committed:
                original_commit(db)
            raise error
        return original_commit(db)

    monkeypatch.setattr(sf.class_, "commit", commit)
    monkeypatch.setattr(
        workflow_engine.workflow_engine,
        "run_sandbox",
        lambda *_args, **_kwargs: pytest.fail("an ambiguous start cannot execute business work"),
    )
    with pytest.raises(OperationalError) as caught:
        _run_sandbox(workflow_id)
    assert caught.value is error and len(attempts) == 1
    with sf() as db:
        rows = db.query(models.WorkflowExecution).all()
        assert len(rows) == int(committed)
        if committed:
            assert rows[0].id == attempts[0]
            assert rows[0].status == "failed" and rows[0].completed_at is not None
            assert rows[0].error_message == str(error)


@pytest.mark.parametrize("winner", ["completed", "failed"])
def test_recovery_cannot_overwrite_a_concurrently_persisted_terminal(
    workflow_database, monkeypatch, winner
):
    sf = workflow_database
    workflow_id = _workflow(sf)
    monkeypatch.setattr(workflow_event_runner, "get_session_factory", lambda: sf)
    original_error = ValueError("late worker error after another terminal")
    calls = []

    def finish_elsewhere(db, *_args, **_kwargs):
        row = db.query(models.WorkflowExecution).filter_by(workflow_id=workflow_id).one()
        calls.append(int(row.id))
        with sf() as other:
            other.execute(
                update(models.WorkflowExecution)
                .where(models.WorkflowExecution.id == row.id)
                .values(
                    status=winner,
                    output_data='{"source":"original_terminal"}',
                    error_message="original terminal evidence",
                    completed_at=datetime.now(UTC),
                )
            )
            other.commit()
        raise original_error

    monkeypatch.setattr(workflow_engine.workflow_engine, "run_sandbox", finish_elsewhere)
    with pytest.raises(ValueError) as caught:
        _run_sandbox(workflow_id)
    assert caught.value is original_error and len(calls) == 1
    with sf() as db:
        row = db.get(models.WorkflowExecution, calls[0])
        assert row.status == winner
        assert row.output_data == '{"source":"original_terminal"}'
        assert row.error_message == "original terminal evidence"


@pytest.mark.skipif(
    not os.getenv("RETORT_TEST_POSTGRES_DSN"), reason="isolated PostgreSQL required"
)
def test_postgres_aborted_sandbox_transaction_persists_original_failure(monkeypatch):
    url = os.environ["RETORT_TEST_POSTGRES_DSN"]
    admin = create_engine(url)
    assert admin.dialect.name == "postgresql"
    schema = f"workflow_tx_{uuid4().hex}"
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        tables = [
            models.User,
            models.Workflow,
            models.WorkflowNode,
            models.WorkflowEdge,
            models.WorkflowExecution,
            models.WorkflowSandboxRun,
            models.OutboxEvent,
        ]
        models.Base.metadata.create_all(engine, tables=[item.__table__ for item in tables])
        sf = sessionmaker(bind=engine)
        with sf() as db:
            db.add(models.User(id=1, username="postgres-transaction", password_hash="synthetic"))
            db.commit()
        workflow_id = _workflow(sf)
        monkeypatch.setattr(workflow_event_runner, "get_session_factory", lambda: sf)
        monkeypatch.setattr(workflow_engine, "get_session_factory", lambda: sf)
        failures = []

        def fail(db, *_args, **_kwargs):
            try:
                # A real server statement error poisons the transaction until
                # ROLLBACK; this is not a mock SQLAlchemy exception.
                db.execute(text("SELECT 1 / 0"))
            except DBAPIError as exc:
                failures.append(exc)
                raise

        monkeypatch.setattr(workflow_engine.workflow_engine, "run_sandbox", fail)
        with pytest.raises(DBAPIError) as caught:
            _run_sandbox(workflow_id)
        assert len(failures) == 1 and caught.value is failures[0]
        with sf() as db:
            row = db.query(models.WorkflowExecution).one()
            assert row.workflow_id == workflow_id and row.user_id == 1
            assert row.status == "failed" and row.completed_at is not None
            assert row.error_message == str(failures[0])
            assert json.loads(row.input_data) == {"synthetic": True}
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
