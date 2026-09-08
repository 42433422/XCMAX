from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modstore_server import mac_control_worker as worker
from modstore_server.api.deps import get_db, require_admin
from modstore_server.db.mac_control import MacControlEvent, MacControlTask
from modstore_server.mac_control_api import router
from modstore_server.mac_control_store import accept, acquire, view
from modstore_server.mac_control_transport import ParaUnavailable, choose_device
from modstore_server.models import Base, User


@pytest.fixture
def factory(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(worker, "get_session_factory", lambda: factory)
    monkeypatch.setenv("MODSTORE_MAC_CONTROL_ENABLED", "1")
    monkeypatch.setenv("XCMAX_FACTORY_CAPABILITY_TOKEN", "fixture-only")
    monkeypatch.setenv("MODSTORE_PARA_DEVICE_ID", "mac")
    monkeypatch.setenv("MODSTORE_PARA_REPO_URL", "https://github.com/42433422/XCMAX.git")
    yield factory
    engine.dispose()


def request():
    return {"message": "Inspect fixture", "target": "mac", "mode": "review"}


def device(**overrides):
    row = {
        "id": "mac",
        "status": "online",
        "lastSeen": datetime.now(UTC).isoformat(),
        "capabilities": {
            "platform": "macos",
            "control_reports": True,
            "supports_exact_commit": True,
            "tool_preflight": {"codex": {"ok": True, "checked_at": datetime.now(UTC).isoformat()}},
        },
        "tools": [{"toolName": "codex", "status": "idle"}],
    }
    return {**row, **overrides}


class FakePara:
    records = []
    submitted = 0
    lose_response = False
    offline = False

    def close(self):
        pass

    def devices(self):
        if self.offline:
            raise ParaUnavailable("offline")
        return [device()]

    def tasks(self):
        return self.records

    def task(self, task_id):
        return next(t for t in self.records if t["id"] == task_id)

    def submit(self, body):
        self.submitted += 1
        result = {
            "id": "para-1",
            "title": body["title"],
            "status": "running",
            "subTasks": [],
        }
        self.records.append(result)
        if self.lose_response:
            raise ParaUnavailable("lost_response")
        assert body["auto_merge"] is False
        assert "workspace_path" not in body
        return result


@pytest.fixture
def para(monkeypatch):
    from modstore_server import mac_control_facts

    monkeypatch.setattr(mac_control_facts, "context_facts", lambda db, req: {"sources": []})
    fake = FakePara()
    fake.records = []
    monkeypatch.setattr(worker, "ParaClient", lambda: fake)
    return fake


def test_accept_survives_restart_and_deduplicates(factory):
    with factory() as db:
        first = accept(db, actor="admin:1", key="stable-key", request=request()).id
    with factory() as db:
        assert accept(db, actor="admin:1", key="stable-key", request=request()).id == first
        with pytest.raises(ValueError):
            accept(db, actor="admin:1", key="stable-key", request={"message": "different"})
        assert db.query(MacControlTask).count() == 1
        assert db.query(MacControlEvent).count() == 1


def test_claim_excludes_other_worker(factory):
    with factory() as db:
        task_id = accept(db, actor="a", key="stable-key", request=request()).id
        assert acquire(db, task_id) is not None
    with factory() as db:
        assert acquire(db, task_id) is None


def test_lost_response_reconciles_without_duplicate(factory, para):
    with factory() as db:
        task_id = accept(db, actor="a", key="stable-key", request=request()).id
    para.lose_response = True
    worker.run_mac_control_sync()
    worker.run_mac_control_sync()
    assert para.submitted == 1
    with factory() as db:
        assert db.get(MacControlTask, task_id).para_task_id == "para-1"
    para.records[0]["status"] = "completed"
    worker.run_mac_control_sync()
    with factory() as db:
        result = view(db.get(MacControlTask, task_id))
        assert result["state"] == "execution_completed"
        assert result["delivery"]["status"] == "not_verified"


def test_missing_acceptance_never_resubmits(factory, para):
    with factory() as db:
        row = accept(db, actor="a", key="stable-key", request=request())
        row.attempt_id, row.state = "old-attempt", "dispatching"
        db.commit()
    worker.run_mac_control_sync()
    worker.run_mac_control_sync()
    assert para.submitted == 0


def test_offline_preserves_queued_task(factory, para):
    with factory() as db:
        task_id = accept(db, actor="a", key="stable-key", request=request()).id
    para.offline = True
    worker.run_mac_control_sync()
    assert para.submitted == 0
    para.offline = False
    worker.run_mac_control_sync()
    with factory() as db:
        assert db.get(MacControlTask, task_id).state == "running"


def test_unknown_preflight_and_busy_device_are_rejected():
    assert choose_device([device(capabilities={})], request(), time.time())[0] is None
    assert choose_device([device(status="offline")], request(), time.time())[0] is None


def test_api_requires_admin(factory):
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    assert client.get("/api/admin/mac-control/fleet").status_code == 401


def test_cancel_and_events(factory):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_admin] = lambda: User(id=1, is_admin=True)

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    client = TestClient(app)
    body = {"request_key": "stable-key", "message": "Inspect fixture"}
    first = client.post("/api/admin/mac-control/tasks", json=body)
    assert first.status_code == 202, first.text
    task_id = first.json()["task"]["id"]
    assert client.post("/api/admin/mac-control/tasks", json=body).json()["task"]["id"] == task_id

    assert (
        client.post(f"/api/admin/mac-control/tasks/{task_id}/cancel").json()["task"]["state"]
        == "cancelled"
    )
    detail = client.get(f"/api/admin/mac-control/tasks/{task_id}").json()
    assert len(detail["events"]) == 2
    assert (
        client.get(f"/api/admin/mac-control/tasks/{task_id}?after={detail['cursor']}").json()[
            "events"
        ]
        == []
    )


def test_device_receipts_are_bound_and_never_complete_delivery(factory, monkeypatch):
    from modstore_server.mac_control_receipts import router as receipts_router
    from modstore_server.mac_control_store import digest

    monkeypatch.setenv("MODSTORE_MAC_CONTROL_DEVICE_TOKENS", '{"mac":"fixture-token"}')
    app = FastAPI()
    app.include_router(receipts_router)

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    with factory() as db:
        row = accept(db, actor="admin:1", key="stable-key", request=request())
        row.device_id, row.attempt_id, row.para_task_id = "mac", "a" * 32, "para-1"
        db.commit()
        task_id = row.id
    payload = {
        "correlation_id": task_id,
        "attempt_id": "b" * 32,
        "device_id": "mac",
        "task_id": "para-1",
        "subtask_id": "sub",
        "status": "completed",
        "progress": 100,
    }
    payload["event_id"] = digest(payload)
    client = TestClient(app)
    assert client.post("/api/internal/mac-control/receipts", json=payload).status_code == 401
    headers = {"Authorization": "Bearer fixture-token"}
    result = client.post("/api/internal/mac-control/receipts", json=payload, headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["stale_attempt"] is True
    assert (
        client.post("/api/internal/mac-control/receipts", json=payload, headers=headers).json()[
            "duplicate"
        ]
        is True
    )
    with factory() as db:
        assert db.get(MacControlTask, task_id).state == "queued"
        assert db.query(MacControlEvent).filter_by(state="late_device_evidence").count() == 1


def test_two_tasks_do_not_share_device_workspace(factory, para):
    with factory() as db:
        accept(db, actor="a", key="first-key", request=request())
        second = accept(db, actor="a", key="second-key", request=request()).id
    worker.run_mac_control_sync()
    assert para.submitted == 1
    with factory() as db:
        assert db.get(MacControlTask, second).state == "waiting_device"


def test_no_guest_identity_is_created(monkeypatch):
    from modstore_server.mac_control_transport import ParaClient

    monkeypatch.delenv("MODSTORE_PARA_CONTROL_TOKEN", raising=False)
    with pytest.raises(ParaUnavailable, match="service_identity_not_configured"):
        ParaClient()


@pytest.mark.parametrize("method", ["devices", "tasks", "task", "submit"])
def test_missing_para_result_is_unavailable_not_empty(monkeypatch, method):
    from modstore_server.mac_control_transport import ParaClient

    client = object.__new__(ParaClient)
    monkeypatch.setattr(client, "request", lambda *args: {})
    args = ("task-1",) if method == "task" else ({},) if method == "submit" else ()
    with pytest.raises(ParaUnavailable):
        getattr(client, method)(*args)


def test_windows_probe_uses_fixed_command_and_reuses_receipt(factory):
    from modstore_server.mac_control_preflight import prepare_windows_probe

    class Client:
        submitted = 0

        def request(self, method, path, body=None):
            if method == "POST":
                self.submitted += 1
                assert (
                    body["script"]
                    == "$ErrorActionPreference = 'Stop'; & codex --version; if ($LASTEXITCODE -ne 0) { exit 1 }"
                )
                return {"command": {"id": "probe-1"}}
            return {"command": {"id": "probe-1", "status": "completed", "exit_code": 0}}

    client = Client()
    devices = [device(id="win", capabilities={"platform": "windows"})]
    with factory() as db:
        prepare_windows_probe(db, client, devices, {"target": "windows"})
        prepare_windows_probe(db, client, devices, {"target": "windows"})
        prepare_windows_probe(db, client, devices, {"target": "windows"})
    assert client.submitted == 1
    assert devices[0]["capabilities"]["tool_preflight"]["codex"]["ok"] is True


def test_handoff_requires_source_evidence_and_only_creates_one_child(factory):
    import json

    from modstore_server.mac_control_handoff import schedule_windows_verification

    with factory() as db:
        parent = accept(
            db, actor="a", key="parent-key", request={**request(), "verify_on_windows": True}
        )
        assert schedule_windows_verification(db, parent, {"reports": []})
        assert db.query(MacControlTask).count() == 1
        receipt = {
            "source": "executor_git_readback",
            "pushed": True,
            "commit_sha": "a" * 40,
            "archive_sha256": "b" * 64,
        }
        raw = {"reports": [{"applied": 1, "status": "completed", "report": json.dumps(receipt)}]}
        assert schedule_windows_verification(db, parent, raw) == ""
        assert schedule_windows_verification(db, parent, raw) == ""
        child = db.query(MacControlTask).filter(MacControlTask.id != parent.id).one()
        spec = json.loads(child.request_json)
        assert spec["parent_task_id"] == parent.id
        assert spec["source_sha"] == receipt["commit_sha"]
        assert spec["source_archive_sha256"] == receipt["archive_sha256"]
        assert spec["target"] == "windows"


@pytest.mark.parametrize("raw", ["[]", '{"receipt_events":null}', '{"resolution":42}', "invalid"])
def test_corrupt_customer_evidence_is_unavailable_not_verified(factory, monkeypatch, raw):
    from modstore_server import mac_control_facts
    from modstore_server.models_cs import CustomerServiceTicket

    monkeypatch.setattr(mac_control_facts, "build_standard_delivery_rows", lambda db: [])
    with factory() as db:
        db.add(
            CustomerServiceTicket(
                session_id=1, user_id=1, ticket_no="evidence-fixture", evidence_json=raw
            )
        )
        db.commit()
        row = mac_control_facts.customer_facts(db, customer_id=1)["tickets"][0]
        assert row["error"] == "invalid_delivery_evidence"
        assert row["delivery_verification"]["runtime_business_verified"] is None
        assert row["delivery_verification"]["completed"] is False
