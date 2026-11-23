"""Finalize the already-returned native customer graph without executing it again."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from modstore_server import auth_service, workflow_engine
from modstore_server import workflow_customer_delivery as delivery
from modstore_server import workflow_event_runner as runner
from modstore_server import workflow_execution_feedback as feedback
from modstore_server.infrastructure.db import get_db
from modstore_server.models import (
    CustomerValueReceipt,
    OutboxEvent,
    User,
    Workflow,
    WorkflowEdge,
    WorkflowExecution,
    WorkflowNode,
)
from modstore_server.services.employee import get_default_employee_client
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.sql.dml import Update

from tests import test_workflow_customer_delivery as customer_tests

experiment_run = customer_tests.experiment_run
workflow_experiment = customer_tests.workflow_experiment
execution_experiment = customer_tests.execution_experiment
customer_workflow = customer_tests.customer_workflow


@pytest.fixture
def returned_customer_graph(customer_workflow, monkeypatch):
    env = customer_workflow
    factory = delivery.get_session_factory()
    client = get_default_employee_client()
    execute = client.execute_task
    complete = feedback.complete_execution_feedback
    state = SimpleNamespace(
        env=env,
        factory=factory,
        workflow_id=env["run"]["workflows"][env["customer_id"]],
        native=[],
        feedback=[],
        charged=[],
        inputs={
            "file_path": "inputs/orders.json",
            "customer_delivery": {
                key: env["goal"][key] for key in ("order_no", "customer_goal_id")
            },
        },
    )

    def native(**kwargs):
        state.native.append(kwargs)
        return execute(**kwargs)

    def observed_feedback(db, execution):
        if execution.workflow_id == state.workflow_id:
            state.feedback.append((db, int(execution.id), execution.status))
        return complete(db, execution)

    monkeypatch.setattr(client, "execute_task", native)
    monkeypatch.setattr(feedback, "complete_execution_feedback", observed_feedback)
    monkeypatch.setattr(runner, "get_session_factory", lambda: factory)
    monkeypatch.setattr(
        runner,
        "consume_llm_credit",
        lambda _db, owner, amount: state.charged.append((owner, amount)),
    )

    def run():
        return runner.run_workflow_for_trigger(
            workflow_id=state.workflow_id,
            user_id=env["customer_id"],
            input_data=state.inputs,
        )

    state.run = run
    return state


def _execution(state, db):
    return db.scalar(
        select(WorkflowExecution).where(WorkflowExecution.workflow_id == state.workflow_id)
    )


def _terminal_in_session(state, db):
    return next(
        (
            row
            for row in db.identity_map.values()
            if isinstance(row, WorkflowExecution)
            and row.workflow_id == state.workflow_id
            and row.status == "completed"
        ),
        None,
    )


def _assert_one_original_native_delivery(state, *, completed):
    assert len(state.native) == 1
    with state.factory() as db:
        rows = db.scalars(
            select(WorkflowExecution).where(WorkflowExecution.workflow_id == state.workflow_id)
        ).all()
        assert len(rows) == 1
        execution = rows[0]
        assert execution.user_id == state.env["customer_id"]
        events = db.scalars(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == str(execution.id),
                OutboxEvent.event_name.in_(
                    (delivery.START_EVENT, delivery.CLAIM_EVENT, delivery.PRODUCED_EVENT)
                ),
            )
        ).all()
        assert sorted(row.event_name for row in events) == sorted(
            (delivery.START_EVENT, delivery.CLAIM_EVENT, delivery.PRODUCED_EVENT)
        )
        assert not db.scalars(
            select(CustomerValueReceipt).where(
                CustomerValueReceipt.customer_ref == f"paid-user:{execution.user_id}",
                CustomerValueReceipt.receipt_kind.in_(("acceptance", "outcome")),
            )
        ).all()
        if not completed:
            return execution.status, execution.output_data, execution.completed_at
        binding, produced = delivery.load_completed_delivery(db, execution.id)
        assert binding["customer_delivery"]["execution_id"] == execution.id
        assert execution.status == "completed" and execution.completed_at is not None
        output = json.loads(execution.output_data)
        artifact = produced["artifacts"][0]
    response = state.env["http"].get(
        f"/api/customer-value/workflow-deliveries/{execution.id}/{artifact['artifact_id']}",
        params=customer_tests._query(state.env),
    )
    assert response.status_code == 200, response.text
    assert response.content == (state.env["workspace"] / artifact["output_path"]).read_bytes()
    assert hashlib.sha256(response.content).hexdigest() == artifact["artifact_sha256"]
    return output


@pytest.mark.parametrize("stage", ["update", "feedback", "commit", "commit_ack"])
def test_final_database_failure_finishes_the_returned_customer_graph_once(
    returned_customer_graph, monkeypatch, stage
):
    state = returned_customer_graph
    original_execute = state.factory.class_.execute
    original_commit = state.factory.class_.commit
    original_feedback = feedback.complete_execution_feedback
    error = OperationalError("customer terminal transaction", {}, RuntimeError("controlled loss"))
    attempts = []

    def execute(db, statement, *args, **kwargs):
        if (
            stage == "update"
            and not attempts
            and isinstance(statement, Update)
            and statement.table.name == WorkflowExecution.__tablename__
            and statement.compile().params.get("status") == "completed"
        ):
            attempts.append(db)
            raise error
        return original_execute(db, statement, *args, **kwargs)

    def complete(db, execution):
        result = original_feedback(db, execution)
        if stage == "feedback" and not attempts and execution.status == "completed":
            attempts.append(db)
            raise error
        return result

    def commit(db):
        if stage in {"commit", "commit_ack"} and not attempts and _terminal_in_session(state, db):
            attempts.append(db)
            if stage == "commit_ack":
                original_commit(db)
            raise error
        return original_commit(db)

    monkeypatch.setattr(state.factory.class_, "execute", execute)
    monkeypatch.setattr(state.factory.class_, "commit", commit)
    monkeypatch.setattr(feedback, "complete_execution_feedback", complete)
    result = state.run()
    assert result["ok"] is True and len(attempts) == 1
    assert result["result"] == _assert_one_original_native_delivery(state, completed=True)
    assert state.charged == [(state.env["customer_id"], 1)]
    assert len(state.feedback) == (1 if stage in {"update", "commit_ack"} else 2)
    if stage != "commit_ack":
        assert state.feedback[-1][0] is not attempts[0]


@pytest.mark.parametrize("committed", [False, True])
def test_customer_execute_api_recovers_terminal_without_repeating_billing(
    returned_customer_graph, monkeypatch, committed
):
    from modstore_server import llm_billing
    from modstore_server.workflow_api import execution as execution_api

    state = returned_customer_graph
    original_commit = state.factory.class_.commit
    original_bill = llm_billing.bill_internal_llm_floor
    error = OperationalError("API terminal commit", {}, RuntimeError("controlled acknowledgement"))
    attempts, billed = [], []

    def commit(db):
        if not attempts and _terminal_in_session(state, db) is not None:
            attempts.append(db)
            if committed:
                original_commit(db)
            raise error
        return original_commit(db)

    async def bill(*args, **kwargs):
        billed.append((args, kwargs))
        return await original_bill(*args, **kwargs)

    monkeypatch.setattr(state.factory.class_, "commit", commit)
    monkeypatch.setattr(llm_billing, "bill_internal_llm_floor", bill)
    with state.factory() as db:
        user = db.get(User, state.env["customer_id"])
        token = auth_service.create_access_token(user.id, user.username)

    def database():
        with state.factory() as db:
            yield db

    app = FastAPI()
    app.include_router(execution_api.router, prefix="/workflow")
    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        path = f"/workflow/{state.workflow_id}/execute"
        rejected = client.post(path, json={"input_data": state.inputs})
        assert rejected.status_code == 401 and state.native == billed == []
        response = client.post(
            path,
            json={"input_data": state.inputs},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200, response.text
    assert response.json()["output_data"] == _assert_one_original_native_delivery(
        state, completed=True
    )
    assert len(attempts) == len(billed) == 1 and state.charged == []
    assert billed[0][1]["user_id"] == state.env["customer_id"]
    assert len(state.feedback) == (1 if committed else 2)


@pytest.mark.parametrize("interruption", [asyncio.CancelledError, SystemExit])
def test_customer_graph_is_durable_before_waiting_for_wallet(
    returned_customer_graph, monkeypatch, interruption
):
    from modstore_server import llm_billing
    from modstore_server import workflow_customer_finalization as finalization
    from modstore_server.workflow_api import execution as execution_api
    from modstore_server.workflow_api.schemas import WorkflowExecuteBody
    from starlette.requests import Request

    state = returned_customer_graph
    billed = []

    async def interrupted_wallet(*_args, **kwargs):
        with state.factory() as observer:
            execution = _execution(state, observer)
            event = delivery._event(observer, f"{finalization.RETURNED_EVENT}:{execution.id}")
            billed.append((kwargs["user_id"], execution.status, event is not None))
        raise interruption("request stopped while the original wallet call was in flight")

    monkeypatch.setattr(llm_billing, "bill_internal_llm_floor", interrupted_wallet)
    with state.factory() as db, pytest.raises(interruption):
        asyncio.run(
            execution_api.execute_workflow(
                state.workflow_id,
                WorkflowExecuteBody(input_data=state.inputs),
                Request({"type": "http", "headers": []}),
                db,
                db.get(User, state.env["customer_id"]),
            )
        )
    assert billed == [(state.env["customer_id"], "completed", True)]
    _assert_one_original_native_delivery(state, completed=True)
    assert (
        finalization.recover_returned_customer_workflows(session_factory=state.factory)["completed"]
        == 0
    )
    assert len(state.native) == len(state.feedback) == len(billed) == 1
    assert state.charged == []


@pytest.mark.parametrize("winner", ["completed", "failed"])
def test_finalization_never_overwrites_a_different_original_terminal(
    returned_customer_graph, monkeypatch, winner
):
    state = returned_customer_graph
    original_commit = state.factory.class_.commit
    error = OperationalError("customer terminal commit", {}, RuntimeError("controlled conflict"))
    attempts = []
    winner_output = '{"source":"independent original terminal"}'

    def commit(db):
        execution = _terminal_in_session(state, db)
        if execution is not None and not attempts:
            execution_id = int(execution.id)
            attempts.append(execution_id)
            db.rollback()
            with state.factory() as other:
                other.execute(
                    update(WorkflowExecution)
                    .where(WorkflowExecution.id == execution_id)
                    .values(
                        status=winner,
                        output_data=winner_output,
                        error_message="original terminal preserved",
                        completed_at=datetime.now(UTC),
                    )
                )
                original_commit(other)
            raise error
        return original_commit(db)

    monkeypatch.setattr(state.factory.class_, "commit", commit)
    with pytest.raises(OperationalError) as caught:
        state.run()
    assert caught.value is error and len(attempts) == 1
    status, output, completed = _assert_one_original_native_delivery(state, completed=False)
    assert status == winner and output == winner_output and completed is not None
    assert len(state.feedback) == 1 and state.charged == []


def test_persistent_finalization_failure_preserves_running_and_raises_original_error(
    returned_customer_graph, monkeypatch
):
    state = returned_customer_graph
    original_commit = state.factory.class_.commit
    errors = []

    def commit(db):
        if _terminal_in_session(state, db) is not None:
            error = OperationalError("COMMIT", {}, RuntimeError(f"controlled outage {len(errors)}"))
            errors.append(error)
            raise error
        return original_commit(db)

    monkeypatch.setattr(state.factory.class_, "commit", commit)
    with pytest.raises(OperationalError) as caught:
        state.run()
    assert caught.value is errors[0] and len(errors) == 2
    status, output, completed = _assert_one_original_native_delivery(state, completed=False)
    assert status == "running" and json.loads(output) == {} and completed is None
    assert len(state.feedback) == 2 and state.charged == []


def test_non_database_finalization_failure_is_not_retried(returned_customer_graph, monkeypatch):
    state = returned_customer_graph
    error = ValueError("controlled feedback contract failure")
    calls = []

    def complete(_db, execution):
        calls.append(int(execution.id))
        raise error

    monkeypatch.setattr(feedback, "complete_execution_feedback", complete)
    with pytest.raises(ValueError) as caught:
        state.run()
    assert caught.value is error and len(calls) == 1
    status, output, completed = _assert_one_original_native_delivery(state, completed=False)
    assert status == "running" and json.loads(output) == {} and completed is None
    assert state.charged == []


@pytest.mark.parametrize("entry", ["trigger", "customer_api"])
def test_first_customer_terminal_update_cannot_overwrite_an_existing_terminal(
    returned_customer_graph, monkeypatch, entry
):
    state = returned_customer_graph
    module = runner if entry == "trigger" else workflow_engine
    execute = module.execute_workflow
    observed = []
    winner_output = '{"source":"terminal persisted after the graph returned"}'

    def graph_then_terminal(*args, **kwargs):
        output = execute(*args, **kwargs)
        with state.factory() as db:
            execution = _execution(state, db)
            observed.append(int(execution.id))
            execution.status = "failed"
            execution.output_data = winner_output
            execution.error_message = "original terminal already decided"
            execution.completed_at = datetime.now(UTC)
            db.commit()
        return output

    monkeypatch.setattr(module, "execute_workflow", graph_then_terminal)
    with pytest.raises(ValueError, match="cannot replace an existing terminal"):
        state.run() if entry == "trigger" else state.env["execute"]()
    status, output, completed = _assert_one_original_native_delivery(state, completed=False)
    assert status == "failed" and output == winner_output and completed is not None
    assert len(observed) == 1 and state.feedback == [] and state.charged == []


def test_customer_real_sandbox_final_commit_is_not_recovered(returned_customer_graph, monkeypatch):
    from modstore_server import workflow_customer_finalization as finalization

    state = returned_customer_graph
    original_commit = state.factory.class_.commit
    error = OperationalError("sandbox COMMIT", {}, RuntimeError("controlled sandbox failure"))
    attempts = []

    def commit(db):
        if _terminal_in_session(state, db) is not None:
            attempts.append(db)
            raise error
        return original_commit(db)

    monkeypatch.setattr(state.factory.class_, "commit", commit)
    monkeypatch.setattr(
        finalization,
        "finalize_returned_customer_workflow",
        lambda *_args, **_kwargs: pytest.fail("sandbox cannot enter customer terminal recovery"),
    )
    with pytest.raises(OperationalError) as caught:
        runner.run_recorded_workflow(
            workflow_id=state.workflow_id,
            user_id=state.env["customer_id"],
            input_data=state.inputs,
            real_sandbox=True,
        )
    assert caught.value is error and len(attempts) == 1
    status, output, completed = _assert_one_original_native_delivery(state, completed=False)
    assert status == "running" and json.loads(output) == {} and completed is None
    assert state.charged == []


def test_ordinary_graph_final_commit_is_not_recovered(returned_customer_graph, monkeypatch):
    from modstore_server import workflow_customer_finalization as finalization

    state = returned_customer_graph
    with state.factory() as db:
        workflow = Workflow(user_id=state.env["customer_id"], name="ordinary graph", is_active=True)
        db.add(workflow)
        db.flush()
        first = WorkflowNode(workflow_id=workflow.id, node_type="start", name="start", config="{}")
        last = WorkflowNode(workflow_id=workflow.id, node_type="end", name="end", config="{}")
        db.add_all([first, last])
        db.flush()
        db.add(
            WorkflowEdge(
                workflow_id=workflow.id,
                source_node_id=first.id,
                target_node_id=last.id,
            )
        )
        state.workflow_id = int(workflow.id)
        db.commit()
    original_commit = state.factory.class_.commit
    error = OperationalError("ordinary COMMIT", {}, RuntimeError("controlled ordinary failure"))
    attempts = []

    def commit(db):
        if _terminal_in_session(state, db) is not None:
            attempts.append(db)
            raise error
        return original_commit(db)

    monkeypatch.setattr(state.factory.class_, "commit", commit)
    monkeypatch.setattr(
        finalization,
        "finalize_returned_customer_workflow",
        lambda *_args, **_kwargs: pytest.fail("ordinary graph cannot enter customer recovery"),
    )
    with pytest.raises(OperationalError) as caught:
        runner.run_recorded_workflow(
            workflow_id=state.workflow_id, user_id=state.env["customer_id"], input_data={}
        )
    assert caught.value is error and len(attempts) == 1
    assert state.native == [] and state.charged == []
    with state.factory() as db:
        execution = _execution(state, db)
        assert execution.status == "running" and execution.completed_at is None


def test_produced_file_cannot_complete_a_graph_that_failed_at_end(
    returned_customer_graph, monkeypatch
):
    from modstore_server import workflow_customer_finalization as finalization

    state = returned_customer_graph
    error = RuntimeError("controlled end-node failure after native delivery")

    def fail_end(*_args, **_kwargs):
        raise error

    monkeypatch.setitem(workflow_engine.workflow_engine.executors, "end", fail_end)
    monkeypatch.setattr(
        finalization,
        "finalize_returned_customer_workflow",
        lambda *_args, **_kwargs: pytest.fail("PRODUCED alone cannot complete a failed graph"),
    )
    with pytest.raises(RuntimeError) as caught:
        state.run()
    assert caught.value is error
    status, _output, completed = _assert_one_original_native_delivery(state, completed=False)
    assert status == "failed" and completed is not None and state.charged == []
