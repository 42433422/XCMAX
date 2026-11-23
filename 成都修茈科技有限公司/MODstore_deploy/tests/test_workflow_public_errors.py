"""JWT and signed webhook failures retain private receipts, not raw HTTP errors."""

from __future__ import annotations

import hashlib
import hmac
import json
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exception_handlers import http_exception_handler
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from modstore_server import auth_service, models, webhook_dispatcher, workflow_engine
from modstore_server.eventing.contracts import (
    WORKFLOW_EXECUTION_COMPLETED,
    WORKFLOW_EXECUTION_FAILED,
)
from modstore_server.infrastructure.db import get_db
from modstore_server.webhook_dispatcher import publish_event as publish_workflow_event
from modstore_server.workflow_api import execution, hooks, triggers
from tests import test_retort_workflow_execution as execution_tests
from tests.test_retort_experiment_lifecycle import start
from tests.test_retort_workflow_experiment import observations

experiment_run = execution_tests.experiment_run
workflow_experiment = execution_tests.workflow_experiment
execution_experiment = execution_tests.execution_experiment


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["http", "public_events"])
async def test_actual_jwt_execute_failure_keeps_diagnostics_out_of_public_responses(
    execution_experiment, monkeypatch, boundary
):
    run = execution_experiment
    start(run)
    user_id = run["arms"]["1"]
    workflow_id = run["workflows"][user_id]
    await run["generate"](user_id)
    sf = models.get_session_factory()
    with sf() as db:
        user = db.get(models.User, user_id)
        token = auth_service.create_access_token(user_id, user.username)

    def database():
        with sf() as db:
            yield db

    app = FastAPI()
    app.include_router(execution.router, prefix="/workflow")
    app.dependency_overrides[get_db] = database
    failures, events, envelopes = [], [], []

    class Bus:
        def publish(self, event):
            events.append(event.to_dict())

    def deliver(envelope):
        envelopes.append(envelope)
        return {"ok": True}

    # Restore the real publisher replaced by the shared fixture. Capture its
    # actual bus and webhook projections at the transport boundary, without I/O.
    monkeypatch.setattr(webhook_dispatcher, "publish_event", publish_workflow_event)
    monkeypatch.setattr(webhook_dispatcher, "neuro_bus", Bus())
    monkeypatch.setattr(webhook_dispatcher, "dispatch_event", deliver)
    original_node = workflow_engine.workflow_engine._execute_node

    def database_failure(*_args, **kwargs):
        try:
            kwargs["session"].execute(text("SELECT * FROM private_customer_database_fixture"))
        except OperationalError as exc:
            failures.append(exc)
            raise

    monkeypatch.setattr(workflow_engine.workflow_engine, "_execute_node", database_failure)
    payload = {"private_input": "synthetic original customer work"}
    path = f"/workflow/{workflow_id}/execute"
    credentials = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as client:
        rejected = client.post(path, json={"input_data": payload})
        assert rejected.status_code == 401 and failures == events == envelopes == []
        response = client.post(path, json={"input_data": payload}, headers=credentials)
        assert response.status_code == 500 and len(failures) == 1
        with sf() as db:
            row = db.query(models.WorkflowExecution).filter_by(workflow_id=workflow_id).one()
            assert row.user_id == user_id and row.status == "failed"
            assert row.completed_at is not None and row.error_message == str(failures[0])
            assert "private_customer_database_fixture" in row.error_message
            assert json.loads(row.input_data) == payload
            execution_id = row.id
        measured = observations(run)
        assert len(measured) == 1 and measured[0]["success"] is False
        assert measured[0]["execution_id"] == execution_id
        assert len(events) == len(envelopes) == 1
        assert envelopes[0]["type"] == WORKFLOW_EXECUTION_FAILED
        assert envelopes[0]["aggregate_id"] == str(execution_id)
        public_data = envelopes[0]["data"]
        assert events[0]["payload"] == public_data
        assert public_data["execution_id"] == execution_id
        assert public_data["workflow_id"] == workflow_id and public_data["user_id"] == user_id
        assert public_data["status"] == "failed" and public_data["completed_at"]
        if boundary == "http":
            assert response.json() == {"detail": "工作流执行失败，请查看执行记录"}
        else:
            assert public_data["error"] == "工作流执行失败，请查看执行记录"
        assert "private_customer_database_fixture" not in response.text
        assert "private_customer_database_fixture" not in json.dumps(events + envelopes)

        monkeypatch.setattr(workflow_engine.workflow_engine, "_execute_node", original_node)
        successful = client.post(path, json={"input_data": payload}, headers=credentials)
        assert successful.status_code == 200 and successful.json()["status"] == "completed"
        assert successful.json()["output_data"]["private_input"] == payload["private_input"]
        assert len(failures) == 1 and len(events) == len(envelopes) == 2
        assert envelopes[-1]["type"] == WORKFLOW_EXECUTION_COMPLETED
        assert events[-1]["payload"] == envelopes[-1]["data"]
        assert envelopes[-1]["data"]["error"] == ""
    assert [item["success"] for item in observations(run)] == [False, True]


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["jwt", "signed"])
async def test_actual_webhook_failure_returns_public_message_and_keeps_private_receipt(
    execution_experiment, monkeypatch, entry
):
    run = execution_experiment
    start(run)
    user_id = run["arms"]["1"]
    workflow_id = run["workflows"][user_id]
    await run["generate"](user_id)
    sf = models.get_session_factory()
    secret, trigger_key = "synthetic-workflow-signing-key", uuid4().hex
    with sf() as db:
        user = db.get(models.User, user_id)
        token = auth_service.create_access_token(user_id, user.username)
        db.add(
            models.WorkflowTrigger(
                workflow_id=workflow_id,
                user_id=user_id,
                trigger_type="webhook",
                trigger_key=trigger_key,
                config_json=json.dumps({"secret": secret}),
                is_active=True,
            )
        )
        db.commit()

    def database():
        with sf() as db:
            yield db

    app = FastAPI()
    app.include_router(triggers.router, prefix="/workflow")
    app.include_router(hooks.workflow_hooks_router)
    app.dependency_overrides[get_db] = database
    causes, failures = [], []

    @app.exception_handler(HTTPException)
    async def remember_cause(request, exc):
        causes.append(exc.__cause__)
        return await http_exception_handler(request, exc)

    # These HTTP consumers use the ordinary graph path. Neither the fault nor
    # a later successful request should cross into the real/mock sandbox mode.
    monkeypatch.setattr(
        workflow_engine.workflow_engine,
        "run_sandbox",
        lambda *_args, **_kwargs: pytest.fail("webhooks cannot switch sandbox modes"),
    )
    original_node = workflow_engine.workflow_engine._execute_node

    def database_failure(*_args, **kwargs):
        try:
            kwargs["session"].execute(text("SELECT * FROM private_customer_database_fixture"))
        except OperationalError as exc:
            failures.append(exc)
            raise

    monkeypatch.setattr(workflow_engine.workflow_engine, "_execute_node", database_failure)
    payload = {"private_input": "synthetic original customer work"}
    body = json.dumps(payload).encode()
    path = (
        f"/workflow/{workflow_id}/webhook-run"
        if entry == "jwt"
        else f"/api/workflow-hooks/webhook/{trigger_key}"
    )
    credentials = (
        {"Authorization": f"Bearer {token}"}
        if entry == "jwt"
        else {
            "X-Webhook-Signature": "sha256="
            + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        }
    )
    with TestClient(app) as client:
        rejected = client.post(path, content=body, headers={"Content-Type": "application/json"})
        assert rejected.status_code == 401 and failures == []
        response = client.post(
            path, content=body, headers={"Content-Type": "application/json", **credentials}
        )
        assert response.status_code == 500
        assert response.json() == {"detail": "工作流执行失败，请查看执行记录"}
        assert "private_customer_database_fixture" not in response.text
        assert len(failures) == 1 and causes[-1] is failures[0]
        with sf() as db:
            row = db.query(models.WorkflowExecution).filter_by(workflow_id=workflow_id).one()
            assert row.user_id == user_id and row.status == "failed"
            assert row.completed_at is not None and row.error_message == str(failures[0])
            assert "private_customer_database_fixture" in row.error_message
            assert json.loads(row.input_data) == payload
            measured = observations(run)
            assert len(measured) == 1 and measured[0]["success"] is False
            assert measured[0]["execution_id"] == row.id

        monkeypatch.setattr(workflow_engine.workflow_engine, "_execute_node", original_node)
        successful = client.post(
            path, content=body, headers={"Content-Type": "application/json", **credentials}
        )
        assert successful.status_code == 200
        assert successful.json()["ok"] is True
        assert successful.json()["result"]["private_input"] == payload["private_input"]
        assert len(failures) == 1
    with sf() as db:
        rows = (
            db.query(models.WorkflowExecution)
            .filter_by(workflow_id=workflow_id)
            .order_by(models.WorkflowExecution.id)
            .all()
        )
        assert [row.status for row in rows] == ["failed", "completed"]
    assert [item["success"] for item in observations(run)] == [False, True]
