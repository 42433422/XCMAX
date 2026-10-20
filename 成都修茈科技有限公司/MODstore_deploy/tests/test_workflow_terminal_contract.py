"""Actual API must persist and publish graph failure unless end ran."""

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modstore_server.api.deps import _get_current_user
from modstore_server.infrastructure.db import get_db
from modstore_server.workflow_api import execution


@pytest.fixture
def workflow_database(tmp_path, monkeypatch):
    """Inject a private SQLite factory without replacing shared DB engines or paths."""
    from modstore_server import models, workflow_engine

    engine = create_engine(f"sqlite:///{tmp_path / 'workflow.sqlite3'}")
    tables = [
        models.User,
        models.Workflow,
        models.WorkflowNode,
        models.WorkflowEdge,
        models.WorkflowExecution,
    ]
    models.Base.metadata.create_all(engine, tables=[model.__table__ for model in tables])
    sf = sessionmaker(bind=engine)
    with sf() as db:
        db.add(models.User(id=1, username="terminal-contract", password_hash="test-only"))
        db.commit()
    monkeypatch.setattr(workflow_engine, "get_session_factory", lambda: sf)
    monkeypatch.setattr(execution, "get_session_factory", lambda: sf)
    try:
        yield sf
    finally:
        engine.dispose()


@pytest.mark.parametrize("shape", ["cycle", "missing_edge", "valid"])
def test_api_records_failure_instead_of_completed(workflow_database, monkeypatch, shape):
    from modstore_server import models, webhook_dispatcher, workflow_engine

    sf = workflow_database
    with sf() as db:
        workflow = models.Workflow(user_id=1, name="contract", is_active=True)
        db.add(workflow)
        db.flush()
        start = models.WorkflowNode(
            workflow_id=workflow.id, node_type="start", name="start", config="{}"
        )
        end = models.WorkflowNode(workflow_id=workflow.id, node_type="end", name="end", config="{}")
        db.add_all([start, end])
        db.flush()
        if shape != "missing_edge":
            db.add(
                models.WorkflowEdge(
                    workflow_id=workflow.id,
                    source_node_id=start.id,
                    target_node_id=start.id if shape == "cycle" else end.id,
                )
            )
        wid = workflow.id
        db.commit()
    events = []
    monkeypatch.setattr(
        webhook_dispatcher,
        "publish_event",
        lambda name, **kwargs: events.append((name, kwargs)),
    )
    monkeypatch.setattr(execution, "require_llm_credit", lambda *args: None)
    monkeypatch.setattr(workflow_engine, "MAX_NODE_VISITS", 2)

    async def bill(*args, **kwargs):
        return None

    monkeypatch.setattr("modstore_server.llm_billing.bill_internal_llm_floor", bill)

    def database():
        with sf() as db:
            yield db

    app = FastAPI()
    app.include_router(execution.router, prefix="/workflow")
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[_get_current_user] = lambda: SimpleNamespace(id=1)
    with TestClient(app) as client:
        response = client.post(f"/workflow/{wid}/execute", json={"input_data": {}})
    with sf() as db:
        row = db.query(models.WorkflowExecution).one()
        if shape == "valid":
            assert response.status_code == 200
            assert row.status == "completed" and events[-1][0].endswith("completed")
        else:
            assert response.status_code == 500
            assert row.status == "failed" and "did not reach end" in row.error_message
            assert events[-1][0].endswith("failed")
            evidence = json.loads(row.output_data)
            assert evidence["warnings"] and evidence["terminal_reason"]
            assert evidence["partial_output"]["nodes"]
