"""Real SQL lineage with network and generation isolated from customers."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from modstore_server.customer_service_tools import json_dumps, json_loads


def make_ticket(client, monkeypatch, *, private=False):
    from modstore_server.api.deps import get_current_user
    from modstore_server.app import app
    from modstore_server.models import UserMod, get_session_factory
    from tests.test_customer_service_api import _make_user

    user = _make_user("closure_" + uuid.uuid4().hex[:10])
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: user)
    if private:
        with get_session_factory()() as db:
            db.add(UserMod(user_id=user.id, mod_id="taiyangniao-pro"))
            db.commit()
    response = client.post(
        "/api/customer-service/issues/intake",
        json={
            "source": "private_mod_rework" if private else "customer_feedback",
            "source_ref": uuid.uuid4().hex,
            "title": "原问题复现",
            "description": "这个流程的计算结果错误",
            "issue_domain": "custom" if private else "software",
            "target_mod_id": "taiyangniao-pro" if private else "",
            "installed_version": "1.0.0",
        },
    )
    assert response.status_code == 200, response.text
    return user, response.json()["ticket_id"]


def seed_repair(db, ticket):
    from modstore_server.customer_issue_shared_release import record_worker_repair
    from modstore_server.customer_service_orchestrator import (
        apply_customer_ticket_incident_progress,
    )
    from modstore_server.models import EmployeeChangeRequest

    cr = EmployeeChangeRequest(
        source_employee_id="fixture-fix",
        change_kind="code_patch",
        status="applied",
        staged_commit_sha="a" * 40,
    )
    db.add(cr)
    db.flush()
    rows = [
        {
            "role": role,
            "employee_id": "fixture-fix" if role == "fix" else role,
            "ok": True,
            "status": "success",
            "result": {"ok": True, "change_request_id": cr.id} if role == "fix" else {"ok": True},
        }
        for role in ("scout", "fix", "verify")
    ]
    apply_customer_ticket_incident_progress(
        db, ticket_id=ticket.id, event_id=991, team_ok=True, team_rows=rows
    )
    record_worker_repair(db, ticket, 991, rows)
    db.commit()
    return cr


def github_fixture(monkeypatch, *, failure=""):
    from modstore_server import customer_issue_shared_release as shared

    monkeypatch.setattr(
        shared,
        "trusted_host_release",
        lambda sha: {
            "git_sha": sha,
            "source_ref": "main",
            "version": "1.0.1",
            "release_id": "fixture-release",
            "signed_metadata_sha256": "d" * 64,
            "artifacts": [{"sha512": "synthetic-digest", "size": 42}],
        },
    )
    monkeypatch.setattr(shared, "_pulls_for_commit", lambda sha: [{"number": 42}])

    def fetch(url):
        if "/pulls/" in url:
            return {
                "merged": failure != "unmerged",
                "merge_commit_sha": "b" * 40,
                "html_url": "https://github.com/42433422/XCMAX/pull/42",
                "base": {
                    "ref": "customer" if failure == "branch" else "main",
                    "repo": {"full_name": "42433422/XCMAX"},
                },
                "head": {"sha": "a" * 40},
            }
        if "required_status_checks" in url:
            return {"contexts": ["unit-tests"]}
        if "check-runs" in url:
            return {
                "total_count": 1,
                "check_runs": [
                    {
                        "name": "unit-tests",
                        "head_sha": "a" * 40,
                        "status": "completed",
                        "conclusion": "failure" if failure == "ci" else "success",
                    }
                ],
            }
        return {
            "status": "diverged" if failure == "ancestry" else "ahead",
            "merge_base_commit": {"sha": "b" * 40},
        }

    monkeypatch.setattr(shared, "_fetch_json", fetch)


def test_shared_release_requires_real_worker_merge_ci_and_customer_action(client, monkeypatch):
    from modstore_server.models import get_session_factory
    from modstore_server.models_cs import CustomerServiceAction, CustomerServiceTicket

    user, tid = make_ticket(client, monkeypatch)
    github_fixture(monkeypatch)
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, tid)
        seed_repair(db, ticket)
        assert (
            db.query(CustomerServiceAction)
            .filter_by(ticket_id=tid, action_type="issue.repair.result")
            .count()
            == 1
        )
    pending = client.get(
        "/api/customer-service/issues/pending-runtime", params={"host_sha": "c" * 40}
    )
    assert pending.status_code == 200, pending.text
    item = next(row for row in pending.json()["items"] if row["id"] == tid)
    assert item["ready"] and item["verification_mode"] == "customer_confirmation"
    target = item["target"]
    body = {
        key: target[key]
        for key in (
            "host_sha",
            "version",
            "release_id",
            "signed_metadata_sha256",
            "case_id",
        )
    }
    body.update(
        receipt_id="identity-1",
        client_instance_id="client-1",
        customer_confirmed=False,
        confirmation_note="",
    )
    endpoint = f"/api/customer-service/issues/{tid}/runtime-receipt"
    first = client.post(endpoint, json=body)
    assert first.status_code == 200, first.text
    assert first.json()["ticket"]["status"] == "processing"
    assert client.post(endpoint, json=body).json()["receipt"]["replayed"]
    confirmed = {
        **body,
        "receipt_id": "confirmation-1",
        "customer_confirmed": True,
        "confirmation_note": "本人复测原问题已修复",
    }
    complete = client.post(endpoint, json=confirmed)
    assert complete.status_code == 200, complete.text
    assert complete.json()["ticket"]["status"] == "resolved"
    assert client.post(endpoint, json={**confirmed, "version": "other"}).status_code == 409


@pytest.mark.parametrize("failure", ["unmerged", "branch", "ci", "ancestry", "missing_action"])
def test_shared_failure_never_binds_or_resolves(client, monkeypatch, failure):
    from modstore_server.models import get_session_factory
    from modstore_server.models_cs import CustomerServiceTicket

    user, tid = make_ticket(client, monkeypatch)
    github_fixture(monkeypatch, failure=failure)
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, tid)
        if failure != "missing_action":
            seed_repair(db, ticket)
    response = client.get(
        "/api/customer-service/issues/pending-runtime", params={"host_sha": "c" * 40}
    )
    item = next(row for row in response.json()["items"] if row["id"] == tid)
    assert not item["ready"]
    with get_session_factory()() as db:
        assert db.get(CustomerServiceTicket, tid).status == "processing"


@pytest.mark.parametrize("confirmed", [False, True])
def test_private_prerequisite_host_receipt_cannot_finish_private_delivery(
    client, monkeypatch, confirmed
):
    from modstore_server.models import get_session_factory
    from modstore_server.models_cs import CustomerServiceTicket

    user, tid = make_ticket(client, monkeypatch, private=True)
    github_fixture(monkeypatch)
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, tid)
        evidence = json_loads(ticket.evidence_json, {})
        evidence["shared_core_prerequisite"] = True
        ticket.evidence_json = json_dumps(evidence)
        seed_repair(db, ticket)
    pending = client.get(
        "/api/customer-service/issues/pending-runtime", params={"host_sha": "c" * 40}
    )
    assert pending.status_code == 200, pending.text
    assert all(row["id"] != tid for row in pending.json()["items"])
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, tid)
        evidence = json_loads(ticket.evidence_json, {})
        target = evidence["shared_core_prerequisite_release"]
        assert evidence["resolution"]["state"] == "queued_private_production"
    response = client.post(
        f"/api/customer-service/issues/{tid}/runtime-receipt",
        json={
            **{
                key: target[key]
                for key in (
                    "host_sha",
                    "version",
                    "release_id",
                    "signed_metadata_sha256",
                    "case_id",
                )
            },
            "receipt_id": f"prerequisite-{confirmed}",
            "client_instance_id": "private-client",
            "customer_confirmed": confirmed,
            "confirmation_note": "宿主修复已经确认" if confirmed else "",
        },
    )
    assert response.status_code == 409, response.text
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, tid)
        evidence = json_loads(ticket.evidence_json, {})
        assert ticket.status == "processing" and ticket.closed_at is None
        assert evidence["resolution"]["state"] == "queued_private_production"
        assert not evidence.get("host_receipts")


def test_dispatch_failure_written_to_same_owner_only(client, monkeypatch):
    from modstore_server.customer_issue_intake import record_dispatch_failure
    from modstore_server.models import get_session_factory
    from modstore_server.models_cs import CustomerServiceTicket

    user, tid = make_ticket(client, monkeypatch)
    record_dispatch_failure({"ticket_id": tid, "user_id": user.id + 100}, "wrong owner")
    record_dispatch_failure({"ticket_id": tid, "user_id": user.id}, "handler unavailable")
    with get_session_factory()() as db:
        evidence = json_loads(db.get(CustomerServiceTicket, tid).evidence_json, {})
        assert evidence["resolution"]["last_error"] == "handler unavailable"
        assert evidence["resolution"]["state"] == "dispatch_failed"


def test_bundle_selects_exact_module_after_employee_wrapping(client, monkeypatch, tmp_path):
    from modstore_server import customer_service_delivery_api as deliveries
    from modstore_server.models import UserMod, get_session_factory
    from modstore_server.models_cs import CustomerServiceTicket
    from tests.customer_delivery_fixture import signed_artifact

    user, tid = make_ticket(client, monkeypatch, private=True)
    first = signed_artifact(tmp_path, monkeypatch, user.id, tid, mod_id="bundle-main")
    from app.infrastructure.mods import trusted_keys

    first_keys = trusted_keys.TRUSTED_MOD_PUBLIC_KEYS_PEM
    second = signed_artifact(tmp_path, monkeypatch, user.id, tid, mod_id="bundle-employee")
    second["source_employee_pack_id"] = second["id"]
    monkeypatch.setattr(
        trusted_keys,
        "TRUSTED_MOD_PUBLIC_KEYS_PEM",
        (*first_keys, *trusted_keys.TRUSTED_MOD_PUBLIC_KEYS_PEM),
    )
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, tid)
        evidence = json_loads(ticket.evidence_json, {})
        evidence.update(acceptance_status="accepted", runs=[{"session_id": "fixture-generation"}])
        ticket.evidence_json = json_dumps(evidence)
        db.commit()

    async def snapshot(_ticket):
        return {
            "custom_delivery": {
                "artifacts": [{"kind": "module", "id": row["id"]} for row in (first, second)],
                "runs": [{"verified_artifacts": [first, second]}],
            }
        }

    monkeypatch.setattr(deliveries, "_custom_delivery_payload", snapshot)
    endpoint = f"/api/customer-service/custom-deliveries/{tid}/artifacts/module/download"
    assert client.get(endpoint).status_code == 409
    assert client.get(endpoint, params={"artifact_id": "absent"}).status_code == 404
    with get_session_factory()() as db:
        assert (
            db.query(UserMod)
            .filter(UserMod.user_id == user.id, UserMod.mod_id.in_([first["id"], second["id"]]))
            .count()
            == 0
        )
        ticket = db.get(CustomerServiceTicket, tid)
        evidence = json_loads(ticket.evidence_json, {})
        evidence["acceptance_status"] = "pending"
        ticket.evidence_json = json_dumps(evidence)
        db.commit()
    assert client.get(endpoint, params={"artifact_id": second["id"]}).status_code == 409
    with get_session_factory()() as db:
        assert db.query(UserMod).filter_by(user_id=user.id, mod_id=second["id"]).count() == 0
        ticket = db.get(CustomerServiceTicket, tid)
        evidence = json_loads(ticket.evidence_json, {})
        evidence["acceptance_status"] = "accepted"
        ticket.evidence_json = json_dumps(evidence)
        db.commit()
    selected = client.get(endpoint, params={"artifact_id": second["id"]})
    assert selected.status_code == 200, selected.text
    assert selected.content == Path(second["signed_package_path"]).read_bytes()
    assert selected.headers["X-Delivery-Entitlements-Refresh"] == "1"
    assert client.get(endpoint, params={"artifact_id": second["id"]}).status_code == 200
    assert second["id"] in client.get("/api/enterprise/entitled-mod-ids").json()["mod_ids"]
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, tid)
        evidence = json_loads(ticket.evidence_json, {})
        assert {row["kind"] for row in evidence["delivery_artifacts"]} == {"module"}
        assert len(evidence["delivery_artifacts"]) == 2
        assert db.query(UserMod).filter_by(user_id=user.id, mod_id=second["id"]).count() == 1
        assert db.query(UserMod).filter_by(user_id=user.id, mod_id=first["id"]).count() == 0
    first_path = Path(first["signed_package_path"])
    first_path.write_bytes(first_path.read_bytes() + b"invalid-tail")
    assert client.get(endpoint, params={"artifact_id": first["id"]}).status_code == 409
    from modstore_server.api.deps import get_current_user
    from modstore_server.app import app
    from tests.test_customer_service_api import _make_user

    admin = _make_user("other-delivery-admin", admin=True)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: admin)
    assert client.get(endpoint, params={"artifact_id": second["id"]}).status_code == 403
    with get_session_factory()() as db:
        assert db.query(UserMod).filter_by(user_id=admin.id).count() == 0
        assert db.query(UserMod).filter_by(user_id=user.id, mod_id=first["id"]).count() == 0


def test_private_rework_starts_existing_factory_once_and_records_failure(client, monkeypatch):
    from modstore_server import workbench_delivery_bridge as bridge
    from modstore_server.customer_issue_intake import dispatch_pending_issue_events
    from modstore_server.models import get_session_factory
    from modstore_server.models_cs import CustomerServiceTicket

    calls = []

    async def start(owner, payload, **kwargs):
        calls.append((owner, payload, kwargs))
        return {"session_id": kwargs["session_id"], "status": "error"}

    monkeypatch.setattr(bridge, "start_workbench_session_for_user", start)
    user, tid = make_ticket(client, monkeypatch, private=True)
    dispatch_pending_issue_events(tid)
    dispatch_pending_issue_events(tid)
    assert len(calls) == 1 and calls[0][0] == user.id
    assert calls[0][1]["suggested_mod_id"] == "sunbird-attendance-custom"
    assert calls[0][1]["replace"] is True and calls[0][2]["run_inline"] is True
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, tid)
        evidence = json_loads(ticket.evidence_json, {})
        assert ticket.intent == "custom_delivery" and ticket.status == "processing"
        assert len(evidence["runs"]) == 1 and evidence["resolution"]["state"] == "repair_failed"


def test_real_signed_artifact_rejects_tamper_wrong_owner_and_ticket(tmp_path, monkeypatch):
    from modstore_server.customer_delivery_build import read_verified_artifact
    from modstore_server.customer_service_delivery_quality import custom_delivery_gate
    from tests.customer_delivery_fixture import signed_artifact

    record = signed_artifact(tmp_path, monkeypatch, 11, 22)
    raw, signed = read_verified_artifact(record, owner_id=11, ticket_id=22)
    assert signed["package_sha256"] == record["package_sha256"]
    snapshot = {
        "status": "done",
        "intent": "mod",
        "artifact": {"mod_id": record["id"], "validation_summary": {"ok": True}},
        "verified_artifacts": [record],
    }
    assert custom_delivery_gate(snapshot)[0]
    for owner, ticket in [(12, 22), (11, 23)]:
        with pytest.raises(ValueError):
            read_verified_artifact(record, owner_id=owner, ticket_id=ticket)
    Path(record["signed_package_path"]).write_bytes(raw + b"tampered-tail")
    assert not custom_delivery_gate(snapshot)[0]


def test_factory_runs_real_compiler_signer_and_immutable_version(tmp_path, monkeypatch):
    from cryptography.hazmat.primitives import serialization

    from modstore_server.customer_delivery_build import (
        prepare_private_artifact,
        read_verified_artifact,
    )
    from tests.customer_delivery_fixture import persist_private_source, signed_artifact

    signed_artifact(tmp_path, monkeypatch, 11, 22, mod_id="factory-fixture")
    private = serialization.load_pem_private_key(
        (tmp_path / "synthetic-signing-key.pem").read_bytes(), password=None
    )
    public = tmp_path / "synthetic-public.pem"
    public.write_bytes(
        private.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    monkeypatch.setenv("XCAGI_MOD_PUBLIC_KEY", str(public))
    monkeypatch.setenv(
        "MODSTORE_SIGNING_PRIVATE_KEY_PATH", str(tmp_path / "synthetic-signing-key.pem")
    )
    source = tmp_path / "library/factory-fixture"
    manifest = json.loads((source / "manifest.json").read_text())
    manifest["version"] = "1.0.2"
    manifest["frontend"] = {
        "runtime": {
            "sdk_version": 1,
            "source": "frontend/src/index.js",
            "entry": "frontend/runtime/index.js",
        }
    }
    (source / "manifest.json").write_text(json.dumps(manifest))
    frontend = source / "frontend/src"
    frontend.mkdir(parents=True)
    (frontend / "index.js").write_text(
        'export function mount(root,sdk) { root.textContent=String(sdk.version); return () => {root.textContent=""} }'
    )
    evidence = {
        "runtime_mod_id": "factory-fixture",
        "installed_version": "1.0.1",
        "requirements": "show SDK version",
        "delivery_generation": uuid.uuid4().hex,
    }
    snapshot = {"artifact": {"mod_id": "factory-fixture"}}
    source, snapshot = persist_private_source(
        tmp_path,
        monkeypatch,
        source,
        owner=11,
        ticket=22,
        snapshot=snapshot,
        generation=evidence["delivery_generation"],
    )
    frontend = source / "frontend/src"
    original_manifest = (source / "manifest.json").read_bytes()
    built = prepare_private_artifact(22, 11, evidence, snapshot)
    assert (source / "manifest.json").read_bytes() == original_manifest
    assert not (source / "frontend/runtime/index.js").exists()
    raw, signed = read_verified_artifact(built, owner_id=11, ticket_id=22)
    assert "frontend/runtime/index.js" in signed["files_sha256"]
    assert signed["manifest"]["version"] == "1.0.2"
    assert signed["manifest"]["public_listing"] is False
    assert signed["manifest"]["owner_user_id"] == 11
    again = prepare_private_artifact(22, 11, evidence, snapshot)
    assert again["package_sha256"] == built["package_sha256"]
    (frontend / "index.js").write_text(
        'export function mount(root,sdk) { root.textContent="changed"; return () => {} }'
    )
    with pytest.raises(ValueError, match="相同私有包版本"):
        prepare_private_artifact(22, 11, evidence, snapshot)
    assert Path(built["signed_package_path"]).read_bytes() == raw
    monkeypatch.delenv("MODSTORE_SIGNING_PRIVATE_KEY_PATH")
    with pytest.raises(ValueError, match="私钥"):
        prepare_private_artifact(22, 11, evidence, snapshot)


def test_private_catalog_exports_exact_accepted_owner_zip_and_never_source(
    client, monkeypatch, tmp_path
):
    from modstore_server import mod_sync_catalog_api as catalog
    from modstore_server.models import UserMod, get_session_factory
    from modstore_server.models_cs import CustomerServiceTicket
    from tests.customer_delivery_fixture import signed_artifact
    from tests.test_customer_service_api import _make_user

    user, tid = make_ticket(client, monkeypatch, private=True)
    record = signed_artifact(
        tmp_path, monkeypatch, user.id, tid, mod_id="sunbird-attendance-custom"
    )
    monkeypatch.setattr(catalog, "_lib", lambda: tmp_path / "library")
    monkeypatch.setattr(
        catalog,
        "_require_mod_sync_auth",
        lambda token: catalog.SyncAuthContext(user=user, auth_type="jwt"),
    )
    with get_session_factory()() as db:
        db.query(UserMod).filter_by(user_id=user.id).delete()
        ticket = db.get(CustomerServiceTicket, tid)
        ev = json_loads(ticket.evidence_json, {})
        ev.update(
            acceptance_status="accepted",
            delivery_generation="fixture-generation",
            runs=[{"session_id": "fixture-generation", "verified_artifacts": [record]}],
        )
        ticket.evidence_json = json_dumps(ev)
        db.commit()
    listed = client.get("/v1/mod-sync/mods")
    assert listed.status_code == 200, listed.text
    item = next(row for row in listed.json()["data"] if row["id"] == "sunbird-attendance-custom")
    assert (
        item["installable"]
        and item["version"] == "1.0.1"
        and item["package_sha256"] == record["package_sha256"]
    )
    assert "_package_path" not in item
    with get_session_factory()() as db:
        assert db.query(UserMod).filter_by(user_id=user.id).count() == 0
    endpoint = "/v1/mod-sync/export-zip/sunbird-attendance-custom"
    unrelated = Path(record["signed_package_path"]).parent.parent / "old-unrelated-ticket"
    unrelated.mkdir()
    (unrelated / "old-unrelated-ticket-0.0.1.xcmod").write_bytes(b"truncated unrelated ZIP")
    first = client.get(endpoint)
    second = client.get(endpoint)
    assert first.status_code == second.status_code == 200
    assert first.content == second.content == Path(record["signed_package_path"]).read_bytes()
    assert first.headers["x-delivery-ticket-id"] == str(tid)
    assert first.headers["x-delivery-artifact-sha256"] == item["package_sha256"]
    assert first.headers["x-delivery-receipt-token"] != second.headers["x-delivery-receipt-token"]
    with get_session_factory()() as db:
        assert (
            db.query(UserMod).filter_by(user_id=user.id, mod_id="sunbird-attendance-custom").count()
            == 1
        )
    source = tmp_path / "library/sunbird-attendance-custom/manifest.json"
    manifest = json.loads(source.read_text())
    manifest["version"] = "9.0.0"
    source.write_text(json.dumps(manifest))
    assert client.get(endpoint).content == first.content
    other = _make_user("other_" + uuid.uuid4().hex[:8], admin=True)
    monkeypatch.setattr(
        catalog,
        "_require_mod_sync_auth",
        lambda token: catalog.SyncAuthContext(user=other, auth_type="jwt"),
    )
    assert client.get(endpoint).status_code == 403
    monkeypatch.setattr(
        catalog,
        "_require_mod_sync_auth",
        lambda token: catalog.SyncAuthContext(user=user, auth_type="jwt"),
    )
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, tid)
        ev = json_loads(ticket.evidence_json, {})
        ev["delivery_generation"] = "next-production"
        ticket.evidence_json = json_dumps(ev)
        db.commit()
    assert client.get(endpoint).status_code == 409
    item = next(
        row
        for row in client.get("/v1/mod-sync/mods").json()["data"]
        if row["id"] == "sunbird-attendance-custom"
    )
    assert item["installable"] is False and item["publication_status"] == "source_only"


@pytest.mark.parametrize("expected_source", ["run", "accepted_bundle"])
def test_private_catalog_missing_bundle_member_never_shrinks_or_grants(
    client, monkeypatch, tmp_path, expected_source
):
    from modstore_server import mod_sync_catalog_api as catalog
    from modstore_server.models import UserMod, get_session_factory
    from modstore_server.models_cs import CustomerServiceTicket
    from tests.customer_delivery_fixture import signed_artifact

    user, tid = make_ticket(client, monkeypatch, private=True)
    first = signed_artifact(tmp_path, monkeypatch, user.id, tid, mod_id="required-main")
    from app.infrastructure.mods import trusted_keys

    keys = trusted_keys.TRUSTED_MOD_PUBLIC_KEYS_PEM
    second = signed_artifact(tmp_path, monkeypatch, user.id, tid, mod_id="required-employee")
    monkeypatch.setattr(
        trusted_keys,
        "TRUSTED_MOD_PUBLIC_KEYS_PEM",
        (*keys, *trusted_keys.TRUSTED_MOD_PUBLIC_KEYS_PEM),
    )
    monkeypatch.setattr(catalog, "_lib", lambda: tmp_path / "library")
    monkeypatch.setattr(
        catalog,
        "_require_mod_sync_auth",
        lambda token: catalog.SyncAuthContext(user=user, auth_type="jwt"),
    )
    with get_session_factory()() as db:
        db.query(UserMod).filter_by(user_id=user.id).delete()
        ticket = db.get(CustomerServiceTicket, tid)
        evidence = json_loads(ticket.evidence_json, {})
        evidence.update(
            acceptance_status="accepted",
            delivery_generation="fixture-generation",
            runs=[
                {
                    "session_id": "fixture-generation",
                    "verified_artifacts": [first, second] if expected_source == "run" else [first],
                }
            ],
            delivery_artifacts=[first, second],
        )
        ticket.evidence_json = json_dumps(evidence)
        original_evidence = ticket.evidence_json
        db.commit()
    Path(second["signed_package_path"]).unlink()
    response = client.get("/v1/mod-sync/export-zip/required-main")
    assert response.status_code == 409, response.text
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, tid)
        assert ticket.evidence_json == original_evidence
        assert ticket.status == "processing" and ticket.closed_at is None
        assert db.query(UserMod).filter_by(user_id=user.id).count() == 0


def test_private_catalog_recovers_only_exact_persisted_factory_records(
    client, monkeypatch, tmp_path
):
    from modstore_server import customer_delivery_catalog as catalog
    from modstore_server import workbench_api
    from modstore_server.models import get_session_factory
    from modstore_server.models_cs import CustomerServiceTicket
    from tests.customer_delivery_fixture import signed_artifact

    user, tid = make_ticket(client, monkeypatch, private=True)
    record = signed_artifact(tmp_path, monkeypatch, user.id, tid, generation=uuid.uuid4().hex)
    generation = record["generation"]
    store = tmp_path / "workbench"
    store.mkdir()
    monkeypatch.setattr(workbench_api, "_workbench_session_store_dir", lambda: store)
    snapshot = {
        "id": generation,
        "user_id": user.id + 1,
        "status": "done",
        "verified_artifacts": [record],
    }
    path = store / f"{generation}.json"
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, tid)
        evidence = json_loads(ticket.evidence_json, {})
        evidence.update(
            acceptance_status="accepted",
            delivery_generation=generation,
            runs=[{"session_id": generation}],
        )
        ticket.evidence_json = json_dumps(evidence)
        db.commit()
    release = catalog.private_release_rows(user.id, tmp_path / "library")[record["id"]]
    raw = catalog.read_catalog_release(release)
    path.write_text(json_dumps(snapshot))
    with pytest.raises(ValueError, match="完整的正式交付清单"):
        catalog.issue_release_download(release, raw)
    snapshot["user_id"] = user.id
    path.write_text(json_dumps(snapshot))
    headers = catalog.issue_release_download(release, raw)
    assert headers["X-Delivery-Ticket-ID"] == str(tid)
    with get_session_factory()() as db:
        evidence = json_loads(db.get(CustomerServiceTicket, tid).evidence_json, {})
        assert evidence["delivery_artifacts"] == [record]


def test_failed_business_probe_returns_to_original_ticket_once(client, monkeypatch, tmp_path):
    from modstore_server import customer_delivery_receipts, workbench_api
    from modstore_server.customer_delivery_receipts import canonical_sha256
    from modstore_server.models import OutboxEvent, get_session_factory
    from modstore_server.models_cs import CustomerServiceTicket
    from tests.customer_delivery_fixture import signed_artifact

    user, tid = make_ticket(client, monkeypatch, private=True)
    record = signed_artifact(
        tmp_path, monkeypatch, user.id, tid, mod_id="sunbird-attendance-custom"
    )

    async def snapshot(sid, owner):
        return {
            "status": "done",
            "intent": "mod",
            "artifact": {"mod_id": record["id"], "validation_summary": {"ok": True}},
            "verified_artifacts": [record],
        }

    monkeypatch.setattr(workbench_api, "get_workbench_session_snapshot", snapshot)
    monkeypatch.setattr(
        customer_delivery_receipts,
        "trusted_host_release",
        lambda sha: {"git_sha": sha, "source_ref": "main"},
    )
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, tid)
        evidence = json_loads(ticket.evidence_json, {})
        evidence.update(
            acceptance_status="accepted",
            delivery_generation="fixture-generation",
            runs=[{"session_id": "fixture-generation", "verified_artifacts": [record]}],
        )
        ticket.evidence_json = json_dumps(evidence)
        db.commit()
    download = client.get(
        f"/api/customer-service/custom-deliveries/{tid}/artifacts/module/download"
    )
    assert download.status_code == 200, download.text
    endpoint = f"/api/customer-service/custom-deliveries/{tid}/installed"
    body = {
        "artifact_kind": "module",
        "artifact_id": record["id"],
        "installed_version": record["version"],
        "receipt_token": download.headers["x-delivery-receipt-token"],
        "receipt_id": "install-failed-probe",
        "stage": "installed",
        "package_sha256": record["package_sha256"],
        "client_instance_id": "fixture-client",
    }
    assert client.post(endpoint, json=body).status_code == 200
    probe = {
        "case_id": "fixture-case",
        "passed": False,
        "observations": {"expected_rows": 2, "actual_rows": 0},
        "observed_at": "2026-09-06T00:00:00Z",
    }
    failure = {
        **body,
        "receipt_id": "failed-probe-1",
        "stage": "verification_failed",
        "host_sha": "c" * 40,
        "runtime_files_sha256": record["runtime_files_sha256"],
        "business_verification": {**probe, "evidence_sha256": canonical_sha256(probe)},
    }
    failed = client.post(endpoint, json=failure)
    assert failed.status_code == 200, failed.text
    assert failed.json()["receipt"]["record"]["failure_recorded"] is True
    assert (
        failed.json()["status"] == "processing"
        and failed.json()["custom_delivery"]["stage"] == "rework"
    )
    replay = client.post(endpoint, json=failure)
    assert replay.status_code == 200, replay.text
    assert replay.json()["receipt"]["replayed"] is True
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, tid)
        evidence = json_loads(ticket.evidence_json, {})
        assert evidence["automatic_rework_generations"] == ["fixture-generation"]
        assert evidence["resolution"]["state"] == "queued_rework"
        from modstore_server.customer_delivery_sources import (
            create_private_source_scope,
            private_source_context,
            seed_previous_delivery,
        )

        # The normal download reduced this list to identity fields. Recover the
        # failed artifact from this ticket's persisted verified production run.
        assert not evidence["delivery_artifacts"][0].get("signed_package_path")
        scope = create_private_source_scope(user.id, uuid.uuid4().hex, tid)
        seed_previous_delivery(scope, evidence)
        with private_source_context(scope) as source_library:
            restored = source_library / record["id"] / "backend/probe.py"
            assert (
                restored.read_bytes()
                == (tmp_path / "library" / record["id"] / "backend/probe.py").read_bytes()
            )
            namespace = {}
            exec(restored.read_text(), namespace)
            assert namespace["verify_delivery"](None)["observations"]["rows"] == 2
        missing = {**evidence, "runs": []}
        with pytest.raises(ValueError, match="可信源码记录"):
            seed_previous_delivery(
                create_private_source_scope(user.id, uuid.uuid4().hex, tid), missing
            )
        conflict = {
            **evidence,
            "delivery_artifacts": [
                {**evidence["delivery_artifacts"][0], "package_sha256": "0" * 64}
            ],
        }
        with pytest.raises(ValueError, match="可信源码记录"):
            seed_previous_delivery(
                create_private_source_scope(user.id, uuid.uuid4().hex, tid), conflict
            )
        rows = (
            db.query(OutboxEvent).filter(OutboxEvent.aggregate_id.like("%runtime-failed:%")).all()
        )
        assert len(rows) == 1
        from modstore_server.customer_delivery_failure import apply_runtime_failure

        next_failure = {**failed.json()["receipt"]["record"], "generation": "next-generation"}
        apply_runtime_failure(db, ticket, evidence, next_failure)
        assert evidence["resolution"]["state"] == "repair_failed"
        assert evidence["automatic_rework_generations"] == ["fixture-generation"]


def test_invalid_archive_is_explicit_delivery_rejection():
    from modstore_server.customer_delivery_package import verify_delivery_package

    with pytest.raises(ValueError):
        verify_delivery_package(b"not an archive")
