from __future__ import annotations

import hashlib
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modstore_server.api.deps import get_db
from modstore_server.db.mac_control import MacControlTask
from modstore_server.mac_control_api import router as admin_router
from modstore_server.mac_control_dispatch_api import SERVICE_ACTOR, router
from modstore_server.mac_control_store import accept
from modstore_server.models import Base

TOKEN = "t" * 48
ROTATED = "r" * 48


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture
def setup(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setenv("MODSTORE_MAC_CONTROL_ENABLED", "1")
    monkeypatch.setenv("XCMAX_FACTORY_CAPABILITY_TOKEN", "fixture-only")
    monkeypatch.setenv("MODSTORE_PARA_DISPATCH_TOKEN_SHA256", digest(TOKEN))

    def database():
        with factory() as db:
            yield db

    app = FastAPI()
    app.include_router(router)
    app.include_router(admin_router)
    app.dependency_overrides[get_db] = database
    yield TestClient(app), factory
    engine.dispose()


def auth(token: str = TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


def body(**overrides) -> dict:
    return {"request_key": "gh-issue-2234-1", "message": "fix issue", **overrides}


def test_rejects_missing_or_wrong_token(setup):
    client, _ = setup
    assert client.post("/api/service/mac-control/tasks", json=body()).status_code == 401
    assert (
        client.post("/api/service/mac-control/tasks", json=body(), headers=auth("x" * 48))
    ).status_code == 401


def test_unconfigured_token_fails_closed(setup, monkeypatch):
    client, _ = setup
    monkeypatch.delenv("MODSTORE_PARA_DISPATCH_TOKEN_SHA256")
    response = client.post("/api/service/mac-control/tasks", json=body(), headers=auth())
    assert response.status_code == 503


def test_creates_code_task_only_for_mac_with_service_actor(setup):
    client, factory = setup
    response = client.post(
        "/api/service/mac-control/tasks",
        json=body(github_issue=2234, mode="review", target="windows"),
        headers=auth(),
    )
    assert response.status_code == 202, response.text
    task_id = response.json()["task"]["id"]
    with factory() as db:
        task = db.get(MacControlTask, task_id)
        request = json.loads(task.request_json)
    assert task.actor == SERVICE_ACTOR
    assert request["mode"] == "code"
    assert request["target"] == "mac"
    assert request["tool"] == "cursor"
    assert request["github_issue"] == 2234
    assert request["ticket_id"] is None and request["customer_id"] is None


def test_idempotent_by_request_key(setup):
    client, _ = setup
    first = client.post("/api/service/mac-control/tasks", json=body(), headers=auth())
    second = client.post("/api/service/mac-control/tasks", json=body(), headers=auth())
    assert first.json()["task"]["id"] == second.json()["task"]["id"]
    conflict = client.post(
        "/api/service/mac-control/tasks", json=body(message="other"), headers=auth()
    )
    assert conflict.status_code == 409


def test_disabled_mac_control_returns_503(setup, monkeypatch):
    client, _ = setup
    monkeypatch.setenv("MODSTORE_MAC_CONTROL_ENABLED", "0")
    response = client.post("/api/service/mac-control/tasks", json=body(), headers=auth())
    assert response.status_code == 503


def test_token_rotation_accepts_any_configured_digest(setup, monkeypatch):
    client, _ = setup
    monkeypatch.setenv("MODSTORE_PARA_DISPATCH_TOKEN_SHA256", f"{digest(TOKEN)}, {digest(ROTATED)}")
    assert (
        client.post("/api/service/mac-control/tasks", json=body(), headers=auth(ROTATED))
    ).status_code == 202
    monkeypatch.setenv("MODSTORE_PARA_DISPATCH_TOKEN_SHA256", digest(ROTATED))
    assert (
        client.post("/api/service/mac-control/tasks", json=body(), headers=auth(TOKEN))
    ).status_code == 401


def test_cannot_read_tasks_created_by_other_actors(setup):
    client, factory = setup
    with factory() as db:
        admin_task = accept(
            db, actor="admin:1", key="admin-request-1", request={"message": "x", "mode": "code"}
        )
        admin_task_id = admin_task.id
    response = client.get(f"/api/service/mac-control/tasks/{admin_task_id}", headers=auth())
    assert response.status_code == 404


def test_reads_own_task_without_customer_facts(setup):
    client, _ = setup
    created = client.post("/api/service/mac-control/tasks", json=body(), headers=auth())
    task_id = created.json()["task"]["id"]
    response = client.get(f"/api/service/mac-control/tasks/{task_id}", headers=auth())
    assert response.status_code == 200
    task = response.json()["task"]
    assert task["state"] == "queued" and task["terminal"] is False
    assert "request" not in task and "facts" not in task


def test_service_token_is_not_an_admin_credential(setup):
    client, _ = setup
    # Admin routes resolve the real require_admin dependency, which rejects this token.
    listed = client.get("/api/admin/mac-control/tasks", headers=auth())
    created = client.post("/api/admin/mac-control/tasks", headers=auth(), json=body())
    assert listed.status_code in {401, 403}
    assert created.status_code in {401, 403}
