"""Recovery uses a fresh transaction and never replays a workflow or a terminal."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from modstore_server import auth_service, models, workflow_engine, workflow_event_runner
from modstore_server import workflow_execution_feedback as feedback
from modstore_server.infrastructure.db import get_db
from modstore_server.workflow_api import execution as execution_api
from tests import test_retort_workflow_execution as execution_tests
from tests import test_workflow_terminal_contract as terminal_tests
from tests.test_retort_experiment_lifecycle import start
from tests.test_retort_workflow_experiment import observations

experiment_run = execution_tests.experiment_run
workflow_experiment = execution_tests.workflow_experiment
execution_experiment = execution_tests.execution_experiment
workflow_database = terminal_tests.workflow_database


@pytest.fixture
def jwt_failure_execution(execution_experiment, monkeypatch):
    run = execution_experiment
    user_id = run["arms"]["1"]
    workflow_id = run["workflows"][user_id]
    sf = models.get_session_factory()
    with sf() as db:
        user = db.get(models.User, user_id)
        token = auth_service.create_access_token(user_id, user.username)
    sessions, events, billed = [], [], []

    def database():
        with sf() as db:
            sessions.append(db)
            yield db

    def publish(event_name, **kwargs):
        events.append((event_name, kwargs))

    async def bill(*args, **kwargs):
        billed.append((args, kwargs))

    monkeypatch.setattr("modstore_server.webhook_dispatcher.publish_event", publish)
    monkeypatch.setattr("modstore_server.llm_billing.bill_internal_llm_floor", bill)
    app = FastAPI()
    app.include_router(execution_api.router, prefix="/workflow")
    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        yield {
            "run": run,
            "sf": sf,
            "user_id": user_id,
            "workflow_id": workflow_id,
            "sessions": sessions,
            "events": events,
            "billed": billed,
            "execute": lambda inputs=None: client.post(
                f"/workflow/{workflow_id}/execute",
                json={"input_data": inputs or {}},
                headers={"Authorization": f"Bearer {token}"},
            ),
        }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage",
    [
        "initial_flush",
        "initial_commit",
        "initial_commit_ack",
        "initial_refresh",
        "begin_flush",
        "start_commit",
        "start_commit_ack",
    ],
)
async def test_jwt_admission_failure_recovers_only_the_original_durable_execution(
    jwt_failure_execution, monkeypatch, stage
):
    env = jwt_failure_execution
    run, sf = env["run"], env["sf"]
    start(run)
    await run["generate"](env["user_id"])
    original_begin, original_feedback = (
        feedback.begin_execution_feedback,
        feedback.complete_execution_feedback,
    )
    original_flush, original_commit, original_refresh = (
        sf.class_.flush,
        sf.class_.commit,
        sf.class_.refresh,
    )
    errors, terminals, admitted = [], [], []

    def duplicate(db):
        db.add(models.User(id=env["user_id"], username=uuid4().hex, password_hash="synthetic"))

    def failed(operation):
        try:
            return operation()
        except (IntegrityError, OperationalError) as exc:
            errors.append(exc)
            raise

    def begin(db, execution):
        result = original_begin(db, execution)
        admitted.append(db)
        if stage == "begin_flush":
            duplicate(db)
            failed(lambda: original_flush(db))
        return result

    def flush(db, *args, **kwargs):
        if (
            stage == "initial_flush"
            and not errors
            and any(isinstance(row, models.WorkflowExecution) for row in db.new)
        ):
            duplicate(db)
            return failed(lambda: original_flush(db, *args, **kwargs))
        return original_flush(db, *args, **kwargs)

    def commit(db):
        row = next(
            (
                item
                for item in [*db.new, *db.identity_map.values()]
                if isinstance(item, models.WorkflowExecution)
                and item.workflow_id == env["workflow_id"]
            ),
            None,
        )
        initial = row is not None and not admitted
        admission = db in admitted and row is not None and row.status == "running"
        target = (initial and stage.startswith("initial_commit")) or (
            admission and stage.startswith("start_commit")
        )
        if target and not errors:
            if stage.endswith("_ack"):
                original_commit(db)
                error = OperationalError("COMMIT", {}, RuntimeError("synthetic lost ACK"))
                errors.append(error)
                raise error
            duplicate(db)
            return failed(lambda: original_commit(db))
        return original_commit(db)

    def refresh(db, instance, *args, **kwargs):
        if (
            stage == "initial_refresh"
            and isinstance(instance, models.WorkflowExecution)
            and not errors
        ):
            failed(lambda: db.execute(text("SELECT * FROM private_initial_refresh_fixture")))
        return original_refresh(db, instance, *args, **kwargs)

    def complete(db, execution):
        terminals.append(db)
        return original_feedback(db, execution)

    monkeypatch.setattr(feedback, "begin_execution_feedback", begin)
    monkeypatch.setattr(feedback, "complete_execution_feedback", complete)
    monkeypatch.setattr(sf.class_, "flush", flush)
    monkeypatch.setattr(sf.class_, "commit", commit)
    monkeypatch.setattr(sf.class_, "refresh", refresh)
    monkeypatch.setattr(
        workflow_engine,
        "execute_workflow",
        lambda *_args, **_kwargs: pytest.fail("failed admission must not execute any graph"),
    )
    response = env["execute"]({"original": "unchanged"})
    assert response.status_code == 500
    assert response.json() == {"detail": "工作流执行失败，请查看执行记录"}
    assert len(errors) == 1 and env["billed"] == []
    durable = stage not in {"initial_flush", "initial_commit"}
    with sf() as db:
        rows = db.query(models.WorkflowExecution).filter_by(workflow_id=env["workflow_id"]).all()
        assert len(rows) == int(durable)
        if durable:
            row = rows[0]
            assert row.user_id == env["user_id"] and row.status == "failed"
            assert row.completed_at is not None and row.error_message == str(errors[0])
            assert json.loads(row.input_data) == {"original": "unchanged"}
            assert env["events"][0][1]["data"]["execution_id"] == row.id
    assert len(env["events"]) == len(terminals) == int(durable)
    assert all(db not in env["sessions"] for db in terminals)
    assert len(observations(run)) == int(stage == "start_commit_ack")


async def _failed_jwt_graph(env, monkeypatch):
    run = env["run"]
    run["graph"]["edges"][0]["condition"] = "ready == True"
    start(run)
    await run["generate"](env["user_id"])
    original_engine = workflow_engine.execute_workflow
    attempts, errors = [], []

    def execute(*args, **kwargs):
        attempts.append((args, kwargs))
        try:
            return original_engine(*args, **kwargs)
        except ValueError as exc:
            errors.append(exc)
            raise

    monkeypatch.setattr(workflow_engine, "execute_workflow", execute)
    return attempts, errors


@pytest.mark.asyncio
async def test_jwt_failure_terminal_ack_is_read_back_without_repeating_feedback(
    jwt_failure_execution, monkeypatch
):
    env = jwt_failure_execution
    attempts, errors = await _failed_jwt_graph(env, monkeypatch)
    sf = env["sf"]
    original_commit, original_feedback = sf.class_.commit, feedback.complete_execution_feedback
    commits, feedback_calls = [], []

    def complete(db, execution):
        feedback_calls.append(int(execution.id))
        return original_feedback(db, execution)

    def commit(db):
        row = next(
            (
                item
                for item in db.identity_map.values()
                if isinstance(item, models.WorkflowExecution) and item.status == "failed"
            ),
            None,
        )
        if row is not None:
            commits.append(int(row.id))
            original_commit(db)
            raise OperationalError("COMMIT", {}, RuntimeError("synthetic terminal ACK lost"))
        return original_commit(db)

    monkeypatch.setattr(feedback, "complete_execution_feedback", complete)
    monkeypatch.setattr(sf.class_, "commit", commit)
    response = env["execute"]({"ready": False})
    assert response.status_code == 500 and response.json() == {
        "detail": "工作流执行失败，请查看执行记录"
    }
    assert len(attempts) == len(errors) == len(commits) == len(feedback_calls) == 1
    assert env["billed"] == [] and len(env["events"]) == 1
    with sf() as db:
        row = db.query(models.WorkflowExecution).filter_by(workflow_id=env["workflow_id"]).one()
        assert row.status == "failed" and row.error_message == str(errors[0])
        assert row.id == commits[0] == feedback_calls[0]
    assert len(observations(env["run"])) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["feedback", "commit"])
async def test_jwt_terminal_storage_failure_preserves_original_error_without_false_event(
    jwt_failure_execution, monkeypatch, stage
):
    env = jwt_failure_execution
    attempts, errors = await _failed_jwt_graph(env, monkeypatch)
    sf = env["sf"]
    original_commit, original_feedback = sf.class_.commit, feedback.complete_execution_feedback
    storage_errors = []

    def poison(db):
        db.add(models.User(id=env["user_id"], username=uuid4().hex, password_hash="synthetic"))
        try:
            db.flush()
        except IntegrityError as exc:
            storage_errors.append(exc)
            raise

    def complete(db, execution):
        if stage == "feedback" and execution.status == "failed":
            poison(db)
        return original_feedback(db, execution)

    def commit(db):
        if stage == "commit" and any(
            isinstance(row, models.WorkflowExecution) and row.status == "failed"
            for row in db.identity_map.values()
        ):
            poison(db)
        return original_commit(db)

    monkeypatch.setattr(feedback, "complete_execution_feedback", complete)
    monkeypatch.setattr(sf.class_, "commit", commit)
    with pytest.raises(ValueError) as caught:
        env["execute"]({"ready": False})
    assert len(attempts) == len(errors) == len(storage_errors) == 1
    assert caught.value is errors[0] and caught.value.__cause__ is storage_errors[0]
    assert env["events"] == env["billed"] == observations(env["run"]) == []
    with sf() as db:
        row = db.query(models.WorkflowExecution).filter_by(workflow_id=env["workflow_id"]).one()
        assert row.status == "running" and row.completed_at is None and not row.error_message


@pytest.mark.asyncio
@pytest.mark.parametrize("winner", ["completed", "failed"])
async def test_jwt_late_graph_error_does_not_overwrite_or_publish_another_terminal(
    jwt_failure_execution, monkeypatch, winner
):
    env = jwt_failure_execution
    attempts, errors = await _failed_jwt_graph(env, monkeypatch)
    original_engine = workflow_engine.execute_workflow
    completed_at = datetime.now(UTC)

    def raced(*args, **kwargs):
        try:
            return original_engine(*args, **kwargs)
        except ValueError:
            with env["sf"]() as db:
                db.query(models.WorkflowExecution).filter_by(workflow_id=env["workflow_id"]).update(
                    {
                        "status": winner,
                        "completed_at": completed_at,
                        "error_message": "original winner preserved",
                        "output_data": json.dumps({"original_winner": winner}),
                    }
                )
                db.commit()
            raise

    monkeypatch.setattr(workflow_engine, "execute_workflow", raced)
    response = env["execute"]({"ready": False})
    assert response.status_code == 409
    assert response.json() == {"detail": "执行记录状态已变化，请查看执行记录"}
    assert len(attempts) == len(errors) == 1
    assert env["events"] == env["billed"] == observations(env["run"]) == []
    with env["sf"]() as db:
        row = db.query(models.WorkflowExecution).filter_by(workflow_id=env["workflow_id"]).one()
        assert row.status == winner and row.error_message == "original winner preserved"
        assert json.loads(row.output_data) == {"original_winner": winner}
        assert row.completed_at.replace(tzinfo=UTC) == completed_at


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


@pytest.mark.asyncio
@pytest.mark.parametrize("committed", [False, True])
async def test_blocked_assignment_cannot_publish_a_start_commit_database_error(
    execution_experiment, monkeypatch, committed
):
    run = execution_experiment
    start(run)
    user_id = run["arms"]["1"]
    workflow_id = run["workflows"][user_id]
    await run["generate"](user_id)
    execution_tests.invalidate(run, "authority")
    sf = models.get_session_factory()
    original_commit = sf.class_.commit
    error = OperationalError("COMMIT", {}, RuntimeError("synthetic private database details"))
    attempts = []

    def commit(db):
        row = next(
            (
                item
                for item in db.identity_map.values()
                if isinstance(item, models.WorkflowExecution) and item.workflow_id == workflow_id
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
        lambda *_args, **_kwargs: pytest.fail("a withdrawn assignment cannot execute"),
    )
    with pytest.raises(OperationalError) as caught:
        run["sandbox"](user_id)
    assert caught.value is error and len(attempts) == 1
    with sf() as db:
        rows = db.query(models.WorkflowExecution).filter_by(workflow_id=workflow_id).all()
        assert len(rows) == int(committed)
        if committed:
            assert rows[0].id == attempts[0] and rows[0].status == "failed"
            assert rows[0].error_message == str(error) and rows[0].completed_at is not None
    assert observations(run) == []
    assert len(observations(run, "experiment.execution_archived")) == int(committed)


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
