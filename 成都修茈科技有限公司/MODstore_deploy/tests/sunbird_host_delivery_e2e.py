"""Real signed SUNBIRD package across Market HTTP and fresh host processes.

No production data or outbound services. The only replaced production function
is the independently tested release-ledger resolver; filesystem/DB roots and
the HTTP app composition are isolated fixtures.
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

FHD = Path(__file__).resolve().parents[3] / "FHD"
MID = "sunbird-attendance-custom"
HOST_SHA = "a" * 40
GENERATION = "b" * 32


@pytest.fixture
def delivery(tmp_path, monkeypatch, request):
    monkeypatch.syspath_prepend(str(FHD))
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path / "market-runtime"))
    monkeypatch.setenv("MODSTORE_EVENT_OUTBOX_PATH", str(tmp_path / "events.jsonl"))
    # The production facade establishes the legacy router import ordering.
    importlib.import_module("modstore_server.customer_service_api")
    import modstore_server.account_lifecycle as account_lifecycle
    import modstore_server.db.catalog as catalog_db
    import modstore_server.models_db as models_db
    from modstore_server import (
        auth_service,
        customer_delivery_catalog,
        customer_issue_release_provenance,
        mod_scaffold_runner,
        mod_sync_catalog_api,
        workbench_api,
    )
    from modstore_server.api.deps import get_db
    from modstore_server.api.market_routes import router as market_router
    from modstore_server.customer_delivery_build import prepare_private_artifact
    from modstore_server.customer_issue_api import router as issues_router
    from modstore_server.customer_service_delivery_api import router
    from modstore_server.db.base import Base
    from modstore_server.mod_sync_catalog_api import router as catalog_router
    from modstore_server.models import User
    from modstore_server.models_cs import CustomerServiceSession, CustomerServiceTicket

    key = Ed25519PrivateKey.generate()
    private = tmp_path / "synthetic-private.pem"
    private.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    private.chmod(0o600)
    public = tmp_path / "synthetic-public.pem"
    public.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    monkeypatch.setenv("XCAGI_MOD_PUBLIC_KEY", str(public))
    monkeypatch.setenv("MODSTORE_SIGNING_PRIVATE_KEY_PATH", str(private))
    library = tmp_path / "library"
    shutil.copytree(FHD / "mods" / MID, library / MID, ignore=shutil.ignore_patterns("__pycache__"))
    if getattr(request, "param", "") == "broken-probe":
        probe = library / MID / "backend/sunbird_attendance/verification.py"
        content = probe.read_text()
        assert 'result.get("rows_used_for_template") == 1' in content
        probe.write_text(
            content.replace(
                'result.get("rows_used_for_template") == 1',
                'result.get("rows_used_for_template") == 2',
            )
        )
        manifest_path = library / MID / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "1.0.1"
        manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(mod_scaffold_runner, "modstore_library_path", lambda: library)
    store = tmp_path / "workbench-sessions"
    store.mkdir()
    monkeypatch.setattr(workbench_api, "_workbench_session_store_dir", lambda: store)
    monkeypatch.setattr(workbench_api, "WORKBENCH_SESSIONS", {})
    engine = create_engine(
        f"sqlite:///{tmp_path / 'market.db'}", connect_args={"check_same_thread": False}
    )
    sessions = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(auth_service, "get_session_factory", lambda: sessions)
    monkeypatch.setattr(catalog_db, "get_session_factory", lambda: sessions)
    monkeypatch.setattr(account_lifecycle, "get_session_factory", lambda: sessions)
    monkeypatch.setattr(models_db, "get_session_factory", lambda: sessions)
    monkeypatch.setattr(customer_delivery_catalog, "get_session_factory", lambda: sessions)
    monkeypatch.setattr(mod_sync_catalog_api, "_lib", lambda: library)
    with sessions.begin() as db:
        for uid in (101, 102):
            db.add(
                User(id=uid, username=f"synthetic-{uid}", password_hash="unusable", is_admin=False)
            )
        db.add(CustomerServiceSession(id=1, user_id=101))
        db.add(
            CustomerServiceTicket(
                id=1,
                session_id=1,
                user_id=101,
                ticket_no="SYNTHETIC-SUNBIRD-1",
                intent="custom_delivery",
                title="Original synthetic conversion issue",
                status="processing",
            )
        )
    evidence = {
        "kind": "module",
        "target_mod_id": "taiyangniao-pro",
        "runtime_mod_id": MID,
        "acceptance_status": "accepted",
        "delivery_terms": {"pricing_mode": "initial_included"},
        "delivery_generation": GENERATION,
        "requirements": "Synthetic conversion probe",
    }
    snapshot = {
        "id": GENERATION,
        "user_id": 101,
        "status": "done",
        "intent": "mod",
        "steps": [],
        "artifact": {"mod_id": MID, "validation_summary": {"ok": True}},
    }
    from tests.customer_delivery_fixture import persist_private_source

    _, snapshot = persist_private_source(
        tmp_path,
        monkeypatch,
        library / MID,
        owner=101,
        ticket=1,
        snapshot=snapshot,
        generation=GENERATION,
    )
    record = prepare_private_artifact(1, 101, evidence, snapshot)
    snapshot["verified_artifacts"] = [record]
    workbench_api.WORKBENCH_SESSIONS[GENERATION] = snapshot
    workbench_api._persist_workbench_session_unlocked(GENERATION)
    assert (store / f"{GENERATION}.json").is_file()
    workbench_api.WORKBENCH_SESSIONS.clear()  # API must hydrate the durable snapshot.
    evidence["runs"] = [{"session_id": GENERATION, "verified_artifacts": [record]}]
    with sessions.begin() as db:
        db.get(CustomerServiceTicket, 1).evidence_json = json.dumps(evidence)
    state = {"trusted": False, "lose_running_response": False, "requests": []}
    monkeypatch.setattr(
        customer_issue_release_provenance,
        "resolve_host_release",
        lambda sha: (
            {"git_sha": sha, "source_ref": "main", "fixture": True}
            if state["trusted"] and sha == HOST_SHA
            else None
        ),
    )

    def database():
        with sessions() as db:
            yield db

    app = FastAPI()
    app.dependency_overrides[get_db] = database
    app.include_router(router, prefix="/api/customer-service")
    app.include_router(market_router)
    app.include_router(catalog_router)
    app.include_router(issues_router, prefix="/api/customer-service")

    @app.middleware("http")
    async def lose_one_response(request: Request, call_next):
        body = await request.json() if request.method == "POST" else None
        response = await call_next(request)
        if body:
            state["requests"].append({"body": body, "status": response.status_code})
        if (
            body
            and body.get("stage") == "running"
            and state["lose_running_response"]
            and response.status_code == 200
        ):
            state["lose_running_response"] = False
            return JSONResponse(
                {"detail": "synthetic response loss after server commit"}, status_code=503
            )
        return response

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    tokens = {uid: auth_service.create_access_token(uid, f"synthetic-{uid}") for uid in (101, 102)}
    yield SimpleNamespace(
        root=tmp_path,
        public=public,
        origin=f"http://127.0.0.1:{port}",
        sessions=sessions,
        ticket=CustomerServiceTicket,
        tokens=tokens,
        record=record,
        state=state,
    )
    server.should_exit = True
    thread.join(timeout=10)
    sock.close()
    engine.dispose()
    assert not thread.is_alive()


def host(delivery, action, *, roster=True):
    root = delivery.root / "host"
    for name in ("data", "mods", "workspace"):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / "data/installation-id").write_text("isolated-sunbird-desktop-1")
    output = root / f"{len(list(root.glob('result-*.json')))}.json"
    output = output.with_name("result-" + output.name)
    env = dict(os.environ)
    for name in (
        "DATABASE_URL",
        "XCAGI_DESKTOP_RESOURCES",
        "XCAGI_DISABLE_MODS",
        "GIT_SHA",
        "XCAGI_BUILD_SHA",
    ):
        env.pop(name, None)
    env.update(
        XCAGI_DATA_DIR=str(root / "data"),
        XCAGI_DESKTOP_DATA_DIR=str(root / "data"),
        DATABASE_URL=f"sqlite:///{root / 'accounts.db'}",
        WORKSPACE_ROOT=str(root / "workspace"),
        XCAGI_MODS_ROOT=str(root / "mods"),
        XCAGI_DESKTOP_MODE="0",
        FHD_ALLOW_X_USER_ID_HEADER="0",
        XCAGI_GIT_SHA=HOST_SHA,
        XCAGI_MOD_PUBLIC_KEY=str(delivery.public),
        XCAGI_MARKET_BASE_URL=delivery.origin,
        XCAGI_CATALOG_BASE_URL=delivery.origin + "/v1",
        XCAGI_MOD_CATALOG_URL=delivery.origin,
        NO_PROXY="127.0.0.1,localhost",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONPATH=str(FHD),
    )
    config = {
        "fhd": str(FHD),
        "root": str(root),
        "action": action,
        "roster": roster,
        "token": delivery.tokens[101],
        "ticket": 1,
        "output": str(output),
    }
    result = subprocess.run(
        [
            os.environ.get("FHD_DELIVERY_E2E_PYTHON") or sys.executable,
            str(Path(__file__).with_name("sunbird_host_worker.py")),
        ],
        input=json.dumps(config),
        text=True,
        capture_output=True,
        env=env,
        cwd=root,
        timeout=45,
    )
    output.with_suffix(".stdout").write_text(result.stdout)
    output.with_suffix(".stderr").write_text(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(output.read_text())


def ticket_state(delivery):
    with delivery.sessions() as db:
        ticket = db.get(delivery.ticket, 1)
        return {
            "id": ticket.id,
            "status": ticket.status,
            "closed_at": ticket.closed_at,
            "evidence": json.loads(ticket.evidence_json),
        }


def test_signed_sunbird_install_fresh_process_probe_and_lost_receipt(delivery):
    endpoint = f"{delivery.origin}/api/customer-service/custom-deliveries/1"
    with httpx.Client(trust_env=False) as client:
        assert client.get(endpoint + "/artifacts/module/download").status_code == 401
        assert (
            client.get(
                endpoint + "/artifacts/module/download",
                headers={"Authorization": f"Bearer {delivery.tokens[102]}"},
            ).status_code
            == 404
        )
    installed = host(delivery, "install")
    assert installed["result"]["success"] is True
    assert installed["result"]["runtime_verified"] is False
    assert installed["current"]["owner_scope"] == "tenant:1"
    assert installed["current"]["package_sha256"] == delivery.record["package_sha256"]
    assert installed["current"]["package_version"] == delivery.record["version"]
    assert ticket_state(delivery)["status"] == "processing"
    unknown = host(delivery, "retry")
    assert unknown["pid"] != installed["pid"]
    assert unknown["process_id"] != installed["process_id"]
    assert unknown["before"]["runtime_status"] == "installed"
    assert unknown["current"]["runtime_status"] == "running"
    assert unknown["current"]["runtime_process_id"] == unknown["process_id"]
    assert unknown["api_status"] == {"1": 200, "2": 403}
    assert unknown["result"] == {"installed_reported": 1, "runtime_reported": 0, "pending": 1}
    pending = ticket_state(delivery)
    assert pending["status"] == "processing" and pending["closed_at"] is None
    runtime = unknown["rows"][0]["runtime_payload"]
    assert runtime["runtime_files_sha256"] == delivery.record["runtime_files_sha256"]
    probe = runtime["business_verification"]
    assert probe["passed"] is True
    assert probe["observations"]["rows_matched"] == 1
    assert probe["observations"]["monthly_formulas_link_detail"] is True
    assert probe["observations"]["customer_data_written"] is False
    assert (
        pending["evidence"]["receipt_events"][-1]["blocker"] == "host_release_provenance_unverified"
    )
    delivery.state.update(trusted=True, lose_running_response=True)
    lost = host(delivery, "retry")
    assert lost["result"]["pending"] == 1
    assert lost["rows"][0]["runtime_reported"] is False
    completed = ticket_state(delivery)
    assert completed["status"] == "resolved" and completed["closed_at"]
    recovered = host(delivery, "retry")
    assert recovered["result"] == {"installed_reported": 0, "runtime_reported": 1, "pending": 0}
    assert recovered["rows"][0]["runtime_response"]["receipt"]["replayed"] is True
    assert recovered["rows"][0]["runtime_payload"] == runtime == lost["rows"][0]["runtime_payload"]
    final = ticket_state(delivery)
    assert final["id"] == 1 and len(final["evidence"]["receipt_events"]) == 2
    assert final["evidence"]["resolution"]["state"] == "resolved"
    for event in final["evidence"]["receipt_events"]:
        assert event["owner_user_id"] == 101 and event["generation"] == GENERATION
        assert event["package_sha256"] == delivery.record["package_sha256"]
        assert event["version"] == delivery.record["version"]
    with httpx.Client(trust_env=False) as client:
        assert (
            client.post(
                endpoint + "/installed",
                json=runtime,
                headers={"Authorization": f"Bearer {delivery.tokens[102]}"},
            ).status_code
            == 404
        )
        for field, value in (
            ("installed_version", "9.9.9"),
            ("package_sha256", "f" * 64),
            ("runtime_files_sha256", "e" * 64),
        ):
            altered = dict(runtime, receipt_id=f"tampered-{field}", **{field: value})
            response = client.post(
                endpoint + "/installed",
                json=altered,
                headers={"Authorization": f"Bearer {delivery.tokens[101]}"},
            )
            assert response.status_code == 409, response.text


@pytest.mark.parametrize("delivery", ["broken-probe"], indirect=True)
def test_actual_failed_sunbird_probe_returns_original_ticket_to_rework(delivery):
    from modstore_server.models_webhook import OutboxEvent

    delivery.state["trusted"] = True
    host(delivery, "install")
    failed = host(delivery, "retry")
    row = failed["rows"][0]
    assert row["runtime_payload"]["stage"] == "verification_failed"
    assert row["runtime_payload"]["business_verification"]["passed"] is False
    assert row["runtime_payload"]["business_verification"]["observations"]["rows_matched"] == 1
    assert (
        row["runtime_payload"]["business_verification"]["observations"]["owner_schema_ready"]
        is True
    )
    assert row["failure_reported"] is True and row["runtime_reported"] is False
    final = ticket_state(delivery)
    assert final["id"] == 1 and final["closed_at"] is None
    assert final["status"] != "resolved"
    assert final["evidence"]["resolution"]["state"] == "queued_rework"
    assert final["evidence"]["resolution"]["runtime_failure"]
    with delivery.sessions() as db:
        events = db.query(OutboxEvent).filter_by(event_name="ops.intake.customer_ticket").all()
        assert len(events) == 1
        payload = json.loads(events[0].payload_json)
        assert payload["ticket_id"] == 1 and payload["user_id"] == 101
        assert payload["intake_source"] == "private_mod_rework"
        assert events[0].status == "pending"  # No external dispatcher runs in this fixture.
    request_count = len(delivery.state["requests"])
    duplicate = host(delivery, "retry")
    assert duplicate["result"] == {"installed_reported": 0, "runtime_reported": 0, "pending": 0}
    assert len(delivery.state["requests"]) == request_count


def test_uninitialized_workspace_waits_without_false_failure_receipt(delivery):
    delivery.state["trusted"] = True
    host(delivery, "install", roster=False)
    pending = host(delivery, "retry", roster=False)
    assert pending["roster_exists"] is False
    assert pending["result"] == {"installed_reported": 1, "runtime_reported": 0, "pending": 1}
    assert "runtime_payload" not in pending["rows"][0]
    final = ticket_state(delivery)
    assert final["status"] == "processing"
    assert [row["stage"] for row in final["evidence"]["receipt_events"]] == ["installed"]
    assert not final["evidence"].get("automatic_rework_generations")


def test_open_client_discovers_installs_refreshes_rights_and_retries_without_manual_page(delivery):
    from modstore_server.models import UserMod

    # A new runtime ID has no UserMod yet; discovery must use the accepted owner ticket.
    with delivery.sessions() as db:
        assert db.query(UserMod).filter_by(user_id=101).count() == 0
    with httpx.Client(trust_env=False) as client:
        catalog = client.get(
            delivery.origin + "/v1/mod-sync/mods",
            headers={"Authorization": f"Bearer {delivery.tokens[101]}"},
        )
        assert catalog.status_code == 200, catalog.text
        assert any(row["id"] == MID and row["installable"] for row in catalog.json()["data"])
        foreign = client.get(
            delivery.origin + "/v1/mod-sync/mods",
            headers={"Authorization": f"Bearer {delivery.tokens[102]}"},
        )
        assert foreign.status_code == 200
        assert all(row["id"] != MID for row in foreign.json()["data"])
    first = host(delivery, "autosync")
    assert first["before"] is None
    assert first["result"]["installed"] == [MID], first["result"]
    assert first["current"]["package_sha256"] == delivery.record["package_sha256"]
    assert MID in first["rights"]
    assert first["api_status"] == {"1": 200, "2": 403}
    assert first["result"]["pending"] > 0  # Unknown host remains pending.
    assert ticket_state(delivery)["status"] == "processing"
    delivery.state["trusted"] = True
    final = host(delivery, "autosync")
    assert final["pid"] != first["pid"]
    assert final["result"]["installed"] == []  # Same version and bytes do not download again.
    assert final["result"]["pending"] == 0, final["result"]
    assert ticket_state(delivery)["status"] == "resolved"
    assert len(ticket_state(delivery)["evidence"]["download_grants"]) == 1
    assert len(ticket_state(delivery)["evidence"]["receipt_events"]) == 2
