"""Stable relay requests survive lost responses, competing SQL writers and retention."""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.application.desktop_relay import e2ee
from app.application.mobile_relay_ports import RelayTaskConflict
from app.infrastructure.mobile_relay import repository
from app.services import mobile_relay_service as relay


@pytest.fixture
def keyed_relay(monkeypatch, tmp_path):
    url = f"sqlite:///{tmp_path / 'stable-relay.db'}"
    engines = []

    def new_service():
        # Each service/session opens an independent connection to the same durable database.
        engine = create_engine(url, poolclass=NullPool, connect_args={"timeout": 20})
        engines.append(engine)
        sessions = sessionmaker(bind=engine, expire_on_commit=False)

        @contextmanager
        def database():
            with sessions.begin() as db:
                yield db

        service = relay.MobileRelayService()
        monkeypatch.setattr(service, "_get_db", database)
        monkeypatch.setattr(service, "_notify_task_creator", Mock())
        return service, database

    service, database = new_service()
    monkeypatch.setattr(relay, "get_db", database)
    private_key = e2ee.generate_private_key_b64()
    public_key = e2ee.public_key_b64(private_key)
    desktop = service.register_desktop(
        label="Stable request desktop", device_id="stable-request", public_key=public_key
    )
    assert service.bind_mobile_by_account(
        user_id=7601, username="stable-owner", pairing_code=desktop["pairing_code"]
    )
    envelope, _, _ = e2ee.seal_payload({"message": "Synthetic work"}, public_key)
    context = SimpleNamespace(
        service=service,
        database=database,
        new_service=new_service,
        desktop=desktop,
        public_key=public_key,
        envelope=envelope,
        request={
            "user_id": 7601,
            "relay_id": desktop["relay_id"],
            "kind": "codex.invoke",
            "payload": envelope,
            "client_request_id": "stable-original-turn",
        },
        auth={"relay_id": desktop["relay_id"], "desktop_token": desktop["desktop_token"]},
    )
    try:
        yield context
    finally:
        for engine in engines:
            engine.dispose()


def test_concurrent_stable_request_has_one_sql_insert_and_one_desktop_claim(keyed_relay):
    context = keyed_relay
    with context.database() as db:
        db.execute(text("CREATE TABLE task_effects (kind TEXT NOT NULL)"))
        db.execute(
            text(
                "CREATE TRIGGER count_task_insert AFTER INSERT ON mobile_relay_tasks "
                "BEGIN INSERT INTO task_effects (kind) VALUES ('insert'); END"
            )
        )
        db.execute(
            text(
                "CREATE TRIGGER count_task_claim AFTER UPDATE OF status ON mobile_relay_tasks "
                "WHEN OLD.status = 'queued' AND NEW.status = 'running' "
                "BEGIN INSERT INTO task_effects (kind) VALUES ('claim'); END"
            )
        )
    services = [context.service, context.new_service()[0]]
    barrier = Barrier(2)

    def create(service):
        barrier.wait(timeout=10)
        return service.create_task(**context.request)

    with ThreadPoolExecutor(max_workers=2) as pool:
        created = list(pool.map(create, services))
    assert created[0] == created[1]
    assert created[0]["task_id"].startswith("rk1_")
    assert len(created[0]["task_id"]) == 64
    assert created[0]["client_request_id"] == context.request["client_request_id"]

    def poll(service):
        barrier.wait(timeout=10)
        return service.poll_desktop(**context.auth)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(poll, services))
    assert sum(len(response["tasks"]) for response in claimed) == 1
    with context.database() as db:
        assert db.execute(text("SELECT COUNT(*) FROM mobile_relay_tasks")).scalar_one() == 1
        assert dict(
            db.execute(text("SELECT kind, COUNT(*) FROM task_effects GROUP BY kind")).all()
        ) == {"insert": 1, "claim": 1}
    restarted = context.new_service()[0]
    recovered = restarted.get_task_by_request(
        user_id=7601,
        relay_id=context.desktop["relay_id"],
        client_request_id=context.request["client_request_id"],
    )
    assert recovered["task_id"] == created[0]["task_id"]
    assert recovered["status"] == "running"
    assert restarted.create_task(**context.request) == recovered
    assert restarted.poll_desktop(**context.auth)["tasks"] == []


@pytest.mark.parametrize("conflict", ["kind", "ciphertext", "ephemeral_key", "ref"])
def test_request_identity_rejects_a_different_encrypted_intent(keyed_relay, conflict):
    context = keyed_relay
    original = context.service.create_task(**context.request)
    changed = {**context.request, "payload": dict(context.envelope)}
    if conflict == "kind":
        changed["kind"] = "git.merge"
    else:
        field = {"ciphertext": "ct", "ephemeral_key": "epk", "ref": "ref"}[conflict]
        changed["payload"][field] = "different-encrypted-envelope"
    with pytest.raises(RelayTaskConflict):
        context.new_service()[0].create_task(**changed)
    assert context.service.get_task(user_id=7601, task_id=original["task_id"]) == original
    reordered = {**context.request, "payload": dict(reversed(list(context.envelope.items())))}
    assert context.service.create_task(**reordered) == original


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("queued", "cancelled"),
        ("running", "unknown"),
        ("blocked", "unknown"),
        ("unknown", "unknown"),
        ("completed", "completed"),
        ("failed", "failed"),
        ("cancelled", "cancelled"),
    ],
)
def test_retention_keeps_the_request_tombstone_and_never_recreates_work(
    keyed_relay, state, expected
):
    context = keyed_relay
    task = context.service.create_task(**context.request)
    with context.database() as db:
        db.execute(
            text(
                "UPDATE mobile_relay_tasks SET status = :status, created_at = '2000-01-01', "
                "updated_at = '2000-01-01', claimed_at = '2000-01-01', "
                "completed_at = :completed_at WHERE task_id = :task_id"
            ),
            {
                "status": state,
                "task_id": task["task_id"],
                "completed_at": "2000-01-01"
                if state in {"completed", "failed", "cancelled"}
                else None,
            },
        )
    assert context.service.poll_desktop(**context.auth)["tasks"] == []
    restarted = context.new_service()[0]
    tombstone = restarted.get_task_by_request(
        user_id=7601,
        relay_id=context.desktop["relay_id"],
        client_request_id=context.request["client_request_id"],
    )
    assert tombstone["task_id"] == task["task_id"]
    assert tombstone["client_request_id"] == context.request["client_request_id"]
    assert tombstone["status"] == expected
    assert tombstone["payload"] == tombstone["result"] == {}
    assert bool(tombstone["completed_at"]) == (expected != "unknown")
    other_envelope, _, _ = e2ee.seal_payload({"message": "Different work"}, context.public_key)
    assert restarted.create_task(**{**context.request, "payload": other_envelope}) == tombstone
    with pytest.raises(RelayTaskConflict):
        restarted.create_task(**{**context.request, "kind": "git.merge"})
    assert restarted.poll_desktop(**context.auth)["tasks"] == []
    assert restarted.get_task(user_id=7601, task_id=task["task_id"]) == tombstone
    with context.database() as db:
        assert db.execute(text("SELECT COUNT(*) FROM mobile_relay_tasks")).scalar_one() == 1


def test_reassigned_desktop_cannot_read_cancel_or_claim_the_previous_owners_task(keyed_relay):
    context = keyed_relay
    task = context.service.create_task(**context.request)
    with context.database() as db:
        db.execute(
            text("UPDATE mobile_relay_desktops SET mobile_user_id = 7602 WHERE relay_id = :id"),
            {"id": context.desktop["relay_id"]},
        )
    for uid in (7601, 7602):
        assert context.service.get_task(user_id=uid, task_id=task["task_id"]) is None
        assert context.service.cancel_task(user_id=uid, task_id=task["task_id"]) is None
        assert (
            context.service.get_task_by_request(
                user_id=uid,
                relay_id=context.desktop["relay_id"],
                client_request_id=context.request["client_request_id"],
            )
            is None
        )
    assert context.service.poll_desktop(**context.auth)["tasks"] == []
    assert context.service.create_task(**context.request) is None
    new_task = context.service.create_task(**{**context.request, "user_id": 7602})
    assert new_task["task_id"] != task["task_id"]
    assert new_task["created_by_user_id"] == 7602
    claimed = context.service.poll_desktop(**context.auth)["tasks"]
    assert [item["task_id"] for item in claimed] == [new_task["task_id"]]
    with context.database() as db:
        assert (
            db.execute(
                text("SELECT status FROM mobile_relay_tasks WHERE task_id = :id"),
                {"id": task["task_id"]},
            ).scalar_one()
            == "queued"
        )


def test_lost_http_response_is_recovered_by_exact_key_and_conflicts_are_409(
    keyed_relay, monkeypatch
):
    from app.fastapi_routes import mobile_api_extensions as extensions

    context = keyed_relay
    monkeypatch.setattr(extensions, "MobileRelayService", lambda: context.service)
    user = SimpleNamespace(id=7601, username="owner", is_active=True)
    app = FastAPI()
    app.include_router(extensions.extension_router, prefix="/api/mobile/v1")
    app.dependency_overrides[extensions.get_mobile_user] = lambda: user
    body = {key: value for key, value in context.request.items() if key != "user_id"}
    body["payload"] = {**body["payload"], "user_id": 7602}
    query = {key: body[key] for key in ("relay_id", "client_request_id")}
    endpoint = "/api/mobile/v1/relay/tasks"
    with TestClient(app) as client:
        # The phone loses the first response body, then the server process restarts.
        assert client.post(endpoint, json=body).status_code == 200
        restarted = context.new_service()[0]
        monkeypatch.setattr(extensions, "MobileRelayService", lambda: restarted)
        recovered = client.get(endpoint, params=query)
        assert recovered.status_code == 200, recovered.text
        task = recovered.json()["data"]["task"]
        assert task["client_request_id"] == body["client_request_id"]
        assert task["created_by_user_id"] == 7601
        assert task["payload"]["user_id"] == 7601
        assert task["payload"]["ct"] == body["payload"]["ct"]
        assert task["status"] == "queued"
        assert client.post(endpoint, json=body).json()["data"]["task"] == task
        assert client.get(f"{endpoint}/{task['task_id']}").json()["data"]["task"] == task
        assert client.post(endpoint, json={**body, "kind": "git.merge"}).status_code == 409
        changed = {**body, "payload": {**body["payload"], "ct": "other-ciphertext"}}
        assert client.post(endpoint, json=changed).status_code == 409
        assert (
            client.get(endpoint, params={**query, "client_request_id": "missing"}).status_code
            == 404
        )
        assert (
            client.get(endpoint, params={**query, "relay_id": "different-relay"}).status_code == 404
        )
        user.id = 7602
        assert client.get(endpoint, params=query).status_code == 404
        assert client.get(f"{endpoint}/{task['task_id']}").status_code == 404
        user.id = 0
        assert client.get(endpoint, params=query).status_code == 401
    with context.database() as db:
        assert db.execute(text("SELECT COUNT(*) FROM mobile_relay_tasks")).scalar_one() == 1


@pytest.mark.parametrize("dialect", ["sqlite", "postgres"])
def test_existing_relay_schema_gains_request_identity_without_rewriting_rows(tmp_path, dialect):
    admin_engine = None
    schema = "relay_identity_" + uuid.uuid4().hex
    if dialect == "postgres":
        url = os.environ.get("XCAGI_TEST_AGENT_POSTGRES_URL")
        if not url:
            pytest.skip("requires CI PostgreSQL service")
        admin_engine = create_engine(url)
        with admin_engine.begin() as connection:
            connection.execute(CreateSchema(schema))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'legacy-relay.db'}")
    sessions = sessionmaker(bind=engine)
    try:
        with sessions.begin() as db:
            db.execute(
                text(
                    "CREATE TABLE mobile_relay_tasks ("
                    "task_id VARCHAR(64) PRIMARY KEY, relay_id VARCHAR(64) NOT NULL, "
                    "kind VARCHAR(64) NOT NULL DEFAULT 'codex.invoke', "
                    "payload_json TEXT NOT NULL DEFAULT '{}', "
                    "status VARCHAR(32) NOT NULL DEFAULT 'queued', "
                    "result_json TEXT NOT NULL DEFAULT '{}', created_by_user_id INTEGER, "
                    "created_at VARCHAR(64) NOT NULL, updated_at VARCHAR(64) NOT NULL, "
                    "claimed_at VARCHAR(64), completed_at VARCHAR(64))"
                )
            )
            db.execute(
                text(
                    "INSERT INTO mobile_relay_tasks (task_id, relay_id, created_by_user_id, "
                    "created_at, updated_at) VALUES ('legacy-task', 'legacy-relay', 7601, "
                    "'2026-01-01', '2026-01-01')"
                )
            )
        for _ in range(2):
            with sessions.begin() as db:
                repository.ensure_tables(db)
        with sessions.begin() as db:
            columns = {
                column["name"]
                for column in inspect(db.connection()).get_columns("mobile_relay_tasks")
            }
            assert "client_request_id" in columns
            row = db.execute(text("SELECT * FROM mobile_relay_tasks")).mappings().one()
            assert row["task_id"] == "legacy-task"
            assert row["client_request_id"] == ""
            assert row["status"] == "queued"
            assert row["created_by_user_id"] == 7601
    finally:
        engine.dispose()
        if admin_engine is not None:
            with admin_engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
            admin_engine.dispose()
