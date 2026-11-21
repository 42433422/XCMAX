from __future__ import annotations

import json
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
from modstore_server.mac_control_store import accept, acquire, digest, encoded, view
from modstore_server.mac_control_transport import ParaUnavailable, choose_device, execution_view
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


def test_opencode_policy_applies_to_mac_control_before_first_dispatch(factory, para, monkeypatch):
    monkeypatch.setenv("DEVFLEET_FORCE_OPENCODE", "1")
    row = device()
    row["capabilities"]["tool_preflight"]["opencode"] = {
        "ok": True,
        "checked_at": datetime.now(UTC).isoformat(),
    }
    row["tools"] = [
        {"toolName": "codex", "status": "disabled"},
        {"toolName": "opencode", "status": "idle"},
    ]
    monkeypatch.setattr(para, "devices", lambda: [row])
    submit = para.submit
    submitted_tools = []

    def capture(body):
        submitted_tools.append(body["tool_name"])
        return submit(body)

    monkeypatch.setattr(para, "submit", capture)
    original = {**request(), "tool": "codex"}
    with factory() as db:
        task_id = accept(db, actor="a", key="stable-key", request=original).id
    worker.run_mac_control_sync()
    worker.run_mac_control_sync()
    assert submitted_tools == ["opencode"]
    with factory() as db:
        assert accept(db, actor="a", key="stable-key", request=original).id == task_id


def test_opencode_policy_waits_for_compatible_device_without_replaying_accepted_work(
    factory, para, monkeypatch
):
    with factory() as db:
        task_id = accept(db, actor="a", key="stable-key", request=request()).id
    monkeypatch.setenv("DEVFLEET_FORCE_OPENCODE", "1")
    worker.run_mac_control_sync()
    assert para.submitted == 0
    with factory() as db:
        assert db.get(MacControlTask, task_id).state == "waiting_device"
    monkeypatch.setenv("DEVFLEET_FORCE_OPENCODE", "0")
    para.lose_response = True
    worker.run_mac_control_sync()
    with factory() as db:
        original_attempt = db.get(MacControlTask, task_id).attempt_id
    monkeypatch.setenv("DEVFLEET_FORCE_OPENCODE", "1")
    worker.run_mac_control_sync()
    assert para.submitted == 1
    with factory() as db:
        task = db.get(MacControlTask, task_id)
        assert task.attempt_id == original_attempt and task.para_task_id == "para-1"


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
            db,
            actor="a",
            key="parent-key",
            request={**request(), "verify_on_windows": True},
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
    from modstore_server.models_cs import CustomerServiceSession, CustomerServiceTicket

    monkeypatch.setattr(mac_control_facts, "build_standard_delivery_rows", lambda db: [])
    with factory() as db:
        db.connection().exec_driver_sql("PRAGMA foreign_keys=ON")
        assert db.connection().exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        user = User(username="evidence-fixture", password_hash="fixture")
        db.add(user)
        db.flush()
        session = CustomerServiceSession(user_id=user.id)
        db.add(session)
        db.flush()
        db.add(
            CustomerServiceTicket(
                session_id=session.id,
                user_id=user.id,
                ticket_no="evidence-fixture",
                evidence_json=raw,
            )
        )
        db.commit()
        row = mac_control_facts.customer_facts(db, customer_id=user.id)["tickets"][0]
        assert row["error"] == "invalid_delivery_evidence"
        assert row["delivery_verification"]["runtime_business_verified"] is None
        assert row["delivery_verification"]["completed"] is False


def test_windows_requires_durable_control_report_protocol():
    row = device(id="win")
    row["capabilities"]["platform"] = "windows"
    row["capabilities"].pop("control_reports")
    selected, reason = choose_device([row], {"target": "windows"}, time.time())
    assert selected is None
    assert reason == "waiting_for_control_report_protocol"
    row["capabilities"]["control_reports"] = True
    assert choose_device([row], {"target": "windows"}, time.time()) == (row, "")


@pytest.fixture
def cancellation(factory, para, monkeypatch):
    from modstore_server.mac_control_receipts import router as receipts_router

    monkeypatch.setenv("MODSTORE_MAC_CONTROL_DEVICE_TOKENS", '{"mac":"fixture-token"}')
    app = FastAPI()
    app.include_router(router)
    app.include_router(receipts_router)
    app.dependency_overrides[require_admin] = lambda: User(id=1, is_admin=True)

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    raw = {
        "id": "para-1",
        "status": "running",
        "reports": [],
        "subTasks": [
            {"id": "sub-1", "device_id": "mac", "tool_name": "codex", "status": "running"}
        ],
    }
    with factory() as db:
        task = accept(db, actor="admin:1", key="stop-original", request=request())
        task.device_id, task.attempt_id, task.para_task_id = "mac", "a" * 32, raw["id"]
        task.state, task.snapshot_json = "running", encoded(execution_view(raw))
        db.commit()
        task_id = task.id
    para.records = [raw]
    client = TestClient(app)
    body = {
        "correlation_id": task_id,
        "attempt_id": "a" * 32,
        "device_id": "mac",
        "task_id": "para-1",
        "subtask_id": "sub-1",
        "status": "running",
        "progress": 10,
    }

    def post(payload=None):
        payload = body if payload is None else payload
        return client.post(
            "/api/internal/mac-control/receipts",
            json={**payload, "event_id": digest(payload)},
            headers={"Authorization": "Bearer fixture-token"},
        )

    def cancel():
        response = client.post(f"/api/admin/mac-control/tasks/{task_id}/cancel")
        assert response.json()["task"]["state"] == "cancel_requested"
        return post().json()["control"]

    return client, raw, body, post, cancel


def stopped_receipt(body, control):
    return {
        **body,
        "status": "cancelled",
        "progress": 0,
        "cancellation": {
            "intent_id": control["intent_id"],
            "outcome": "process_exited",
            "usage_status": "unknown",
            "native": {
                "status": "unknown",
                "reason": "codex_cancelled",
                "usage": None,
                "exit_code": None,
                "signal": "SIGKILL",
                "termination_method": "posix_process_group",
            },
        },
    }


def test_cancel_command_is_live_on_duplicate_receipt_and_requires_admin(cancellation):
    client, _, _, post, cancel = cancellation
    assert post().json()["control"] is None
    first = cancel()
    replay = post().json()
    assert replay["duplicate"] is True and replay["control"] == first
    assert cancel() == first
    client.app.dependency_overrides.pop(require_admin)
    assert (
        client.post(f"/api/admin/mac-control/tasks/{first['correlation_id']}/cancel").status_code
        == 401
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("device_id", "other"),
        ("correlation_id", "b" * 32),
        ("attempt_id", "c" * 32),
        ("task_id", "foreign-para"),
        ("subtask_id", "foreign-subtask"),
    ],
)
def test_cancel_command_does_not_cross_original_identity(cancellation, field, value):
    _, _, body, post, cancel = cancellation
    cancel()
    result = post({**body, field: value})
    assert result.status_code != 200 or result.json()["control"] is None


@pytest.mark.parametrize("fault", ["tool", "subtask_device", "duplicate", "missing_native_task"])
def test_cancel_requires_original_native_assignment(cancellation, factory, fault):
    _, raw, body, post, cancel = cancellation
    cancel()
    if fault == "tool":
        raw["subTasks"][0]["tool_name"] = "opencode"
    elif fault == "subtask_device":
        raw["subTasks"][0]["device_id"] = "other"
    elif fault == "duplicate":
        raw["subTasks"].append(dict(raw["subTasks"][0]))
    with factory() as db:
        task = db.get(MacControlTask, body["correlation_id"])
        task.snapshot_json = encoded(execution_view(raw))
        if fault == "missing_native_task":
            task.para_task_id = ""
        db.commit()
    assert post().json()["control"] is None


def test_actual_stop_waits_for_original_native_terminal_and_keeps_usage_unknown(
    cancellation, factory, para
):
    _, raw, body, post, cancel = cancellation
    proof = stopped_receipt(body, cancel())
    assert post(proof).json()["accepted"] is True
    worker.run_mac_control_sync()
    with factory() as db:
        assert db.get(MacControlTask, body["correlation_id"]).state == "cancel_requested"
    raw["status"] = raw["subTasks"][0]["status"] = "failed"
    worker.run_mac_control_sync()
    worker.run_mac_control_sync()
    with factory() as db:
        task = db.get(MacControlTask, body["correlation_id"])
        assert task.state == "cancelled"
        snapshot = json.loads(task.snapshot_json)
        assert snapshot["status"] == "failed"  # The native execution fact is preserved.
        assert snapshot["cancellation"]["usage_status"] == "unknown"
        assert snapshot["cancellation"]["subtasks"]["sub-1"]["native"]["usage"] is None
    assert para.submitted == 0
    assert post(proof).json()["duplicate"] is True


@pytest.mark.parametrize("fault", ["intent", "attempt", "subtask", "signal_only", "usage_zero"])
def test_cancellation_proof_rejects_unbound_or_unconfirmed_stop(cancellation, fault):
    _, _, body, post, cancel = cancellation
    proof = stopped_receipt(body, cancel())
    if fault == "intent":
        proof["cancellation"]["intent_id"] = "0" * 64
    elif fault == "attempt":
        proof["attempt_id"] = "b" * 32
    elif fault == "subtask":
        proof["subtask_id"] = "other"
    elif fault == "signal_only":
        proof["cancellation"]["native"].pop("termination_method")
    else:
        proof["cancellation"]["usage_status"] = "not_started"
    assert post(proof).status_code == 409


def test_cancelled_device_queued_work_never_claims_native_interrupt(cancellation, factory):
    _, raw, body, post, cancel = cancellation
    proof = {
        **body,
        "status": "cancelled",
        "cancellation": {
            "intent_id": cancel()["intent_id"],
            "outcome": "not_started",
            "usage_status": "not_started",
            "native": None,
        },
    }
    assert post(proof).status_code == 200
    raw["status"] = raw["subTasks"][0]["status"] = "failed"
    worker.run_mac_control_sync()
    with factory() as db:
        assert db.get(MacControlTask, body["correlation_id"]).state == "cancelled"


def test_late_cancel_receipt_does_not_replace_actual_native_completion(cancellation, factory):
    _, raw, body, post, cancel = cancellation
    proof = stopped_receipt(body, cancel())
    raw["status"] = raw["subTasks"][0]["status"] = "completed"
    worker.run_mac_control_sync()
    assert post(proof).status_code == 200
    worker.run_mac_control_sync()
    with factory() as db:
        assert db.get(MacControlTask, body["correlation_id"]).state == "execution_completed"


def test_cross_outbox_lost_ack_reconciles_without_another_execution(cancellation, factory, para):
    _, raw, body, post, cancel = cancellation
    control = cancel()
    raw["status"] = raw["subTasks"][0]["status"] = "failed"
    raw["reports"] = [
        {
            "applied": 1,
            "status": "failed",
            "report": encoded(
                {
                    "source": "mac_control_cancel",
                    "control": control,
                    "stop_confirmed": True,
                    "model_usage_settled": False,
                }
            ),
        }
    ]
    worker.run_mac_control_sync()
    worker.run_mac_control_sync()
    with factory() as db:
        task = db.get(MacControlTask, body["correlation_id"])
        assert task.state == "cancel_requested"
        assert task.reason == "waiting_for_original_device_stop_receipt"
    proof = stopped_receipt(body, control)
    assert post(proof).status_code == 200  # Server accepted it; the device may lose this ACK.
    assert post(proof).json()["duplicate"] is True
    worker.run_mac_control_sync()
    with factory() as db:
        assert db.get(MacControlTask, body["correlation_id"]).state == "cancelled"
        assert db.query(MacControlEvent).filter_by(event_key=digest(proof)).count() == 1
    assert para.submitted == 0


@pytest.mark.parametrize(
    "native",
    [
        {"exit_code": False, "signal": None},
        {"exit_code": True, "signal": None},
        {"signal": True},
        {"signal": 9},
        {"signal": ["SIGKILL"]},
        {"signal": "not-a-signal"},
        {"exit_code": 0, "signal": "SIGKILL"},
        {"termination_method": ["posix_process_group"]},
    ],
)
def test_cancel_rejects_non_native_exit_fields(cancellation, native):
    _, _, body, post, cancel = cancellation
    proof = stopped_receipt(body, cancel())
    proof["cancellation"]["native"].update(native)
    assert post(proof).status_code == 409


@pytest.mark.parametrize("invalid_field", [None, "exit_code", "active_tools"])
def test_completed_native_receipt_is_preserved_before_publication_stop(cancellation, invalid_field):
    _, _, body, post, cancel = cancellation
    proof = stopped_receipt(body, cancel())
    proof["cancellation"].update(
        usage_status="known",
        native={
            "status": "completed",
            "turn_completed": True,
            "exit_code": 0,
            "active_tools": 0,
            "signal": None,
            "usage": {"input_tokens": 11, "cached_input_tokens": 1, "output_tokens": 4},
        },
    )
    if invalid_field:
        proof["cancellation"]["native"][invalid_field] = False
    assert post(proof).status_code == (409 if invalid_field else 200)


@pytest.mark.parametrize(
    "other_status,expected",
    [
        ("completed", "cancelled"),
        ("merged", "cancelled"),
        ("cancelled", "cancelled"),
        ("running", "cancel_requested"),
        ("pending", "cancel_requested"),
        ("failed", "failed"),
    ],
)
def test_partial_native_work_keeps_each_original_outcome(
    cancellation, factory, other_status, expected
):
    _, raw, body, post, cancel = cancellation
    control = cancel()
    assert post(stopped_receipt(body, control)).status_code == 200
    raw["status"] = raw["subTasks"][0]["status"] = "failed"
    raw["subTasks"].append(
        {"id": "other", "device_id": "mac", "tool_name": "codex", "status": other_status}
    )
    raw["reports"] = [
        {
            "applied": 1,
            "status": "failed",
            "report": encoded(
                {
                    "source": "mac_control_cancel",
                    "control": control,
                    "stop_confirmed": True,
                }
            ),
        }
    ]
    worker.run_mac_control_sync()
    with factory() as db:
        task = db.get(MacControlTask, body["correlation_id"])
        assert task.state == expected
        assert json.loads(task.snapshot_json)["subtasks"][1]["status"] == other_status
