"""Repair reports are not proof of customer delivery."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import uuid
import zipfile
from types import SimpleNamespace as NS

import pytest
from fastapi import HTTPException

from modstore_server.custom_delivery_incident_policy import apply_ticket_outcome
from modstore_server.customer_delivery_receipts import canonical_sha256, record_receipt
from modstore_server.customer_issue_delivery_contract import (
    execution_succeeded,
    team_succeeded,
)


def test_fix_failure_or_missing_roles_blocks_team():
    assert not team_succeeded([{"role": r, "ok": r != "fix"} for r in ("scout", "fix", "verify")])
    assert not team_succeeded([{"role": "verify", "ok": True}])
    ticket = NS(status="processing", decision_status="pending")
    apply_ticket_outcome(ticket, True, False)
    assert ticket.status == "processing" and ticket.closed_at is None


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"status": "unknown"},
        {"status": "skipped"},
        {"ok": False},
        {"status": "success", "error": "failed"},
        {"ok": True, "results": [{"ok": False}]},
        {"status": "success", "result": {"outputs": [{"ok": False}]}},
    ],
)
def test_no_false_execution_success(value):
    assert not execution_succeeded(value)


def test_o7_error_and_lineage(monkeypatch):
    monkeypatch.setattr(
        "modstore_server.customer_issue_intake.record_dispatch_failure",
        lambda *args: None,
    )
    from modstore_server import employee_orchestrator
    from modstore_server.production_line_orchestrator import (
        ProductionLineOrchestrator,
        StepStatus,
    )

    orch = ProductionLineOrchestrator()
    orch._release_train_subset = True
    cross = []
    orch.register_callback("cross_line_trigger", lambda **kw: cross.append(kw))
    context = {"ticket_id": 45, "tenant_id": 9, "summary": "original"}
    monkeypatch.setattr(
        employee_orchestrator,
        "plan_and_dispatch",
        lambda *a, **kw: {"ok": False, "error": "failure"},
    )
    result = asyncio.run(orch.run_step("O7", context))
    assert result.status == StepStatus.FAILED and not cross
    assert result.data["context"] == context
    monkeypatch.setattr(
        employee_orchestrator,
        "plan_and_dispatch",
        lambda *a, **kw: {"ok": True, "job_id": "job"},
    )
    assert asyncio.run(orch.run_step("O7", context)).status == StepStatus.COMPLETED
    assert all(cross[0][k] == v for k, v in context.items())
    assert cross[0]["result_data"]["result"]["job_id"] == "job"


@pytest.fixture
def receipt_case():
    ticket = NS(
        id=9,
        user_id=11,
        ticket_no="fixture",
        title="original",
        summary="original issue",
        intent="custom_delivery",
        status="processing",
        decision_status="approved",
        closed_at=None,
    )
    artifact = {
        "kind": "module",
        "id": "customer-mod",
        "version": "1.0.1",
        "package_sha256": "a" * 64,
    }
    grant = {
        **artifact,
        "token": "download-token-fixture",
        "owner_user_id": 11,
        "generation": "run-2",
        "verification_case_id": "case-1",
        "runtime_files_sha256": "b" * 64,
    }
    evidence = {
        "acceptance_status": "accepted",
        "delivery_terms": {"pricing_mode": "initial_included"},
        "delivery_generation": "run-2",
        "download_grants": [grant],
        "delivery_artifacts": [artifact],
        "runs": [{"session_id": "run-2", "artifact": {"mod_id": "customer-mod"}}],
    }
    body = {
        "artifact_kind": "module",
        "artifact_id": "customer-mod",
        "installed_version": "1.0.1",
        "receipt_token": "download-token-fixture",
        "receipt_id": "install-1",
        "stage": "installed",
        "package_sha256": "a" * 64,
        "client_instance_id": "client-1",
        "host": "fixture",
        "host_sha": "c" * 40,
        "runtime_files_sha256": "",
        "business_verification": {},
    }
    return ticket, evidence, body


def running(body):
    probe = {
        "case_id": "case-1",
        "passed": True,
        "observations": {"rows": 2},
        "observed_at": "2026-09-06T00:00:00Z",
    }
    return dict(
        body,
        stage="running",
        receipt_id="runtime-1",
        runtime_files_sha256="b" * 64,
        business_verification={**probe, "evidence_sha256": canonical_sha256(probe)},
    )


def test_wrapped_employee_completion_uses_delivered_module_identity(receipt_case, monkeypatch):
    from modstore_server import customer_delivery_receipts as receipts
    from modstore_server.customer_service_delivery_completion import complete_delivery_if_ready

    ticket, evidence, body = receipt_case
    evidence["kind"] = "employee"
    evidence["runs"][-1]["artifact"] = {"pack_id": "customer-mod"}
    evidence["delivery_artifacts"][0]["source_employee_pack_id"] = "customer-mod"
    monkeypatch.setattr(
        receipts, "trusted_host_release", lambda sha: {"git_sha": sha, "source_ref": "main"}
    )
    record_receipt(ticket, evidence, body, owner_id=11)
    complete_delivery_if_ready(ticket, evidence)
    assert ticket.status == "processing"
    record_receipt(ticket, evidence, running(body), owner_id=11)
    complete_delivery_if_ready(ticket, evidence)
    assert ticket.status == "resolved"


def test_bundle_waits_for_wrapped_employee_runtime_on_same_client(receipt_case, monkeypatch):
    from modstore_server import customer_delivery_receipts as receipts
    from modstore_server.customer_service_delivery_completion import complete_delivery_if_ready

    ticket, evidence, body = receipt_case
    evidence["kind"] = "bundle"
    evidence["runs"][-1]["artifact"]["pack_id"] = "wrapped-employee"
    evidence["delivery_artifacts"].append(
        {
            **evidence["delivery_artifacts"][0],
            "id": "wrapped-employee",
            "source_employee_pack_id": "wrapped-employee",
        }
    )
    evidence["download_grants"].append(
        {**evidence["download_grants"][0], "id": "wrapped-employee", "token": "second-grant"}
    )
    monkeypatch.setattr(
        receipts, "trusted_host_release", lambda sha: {"git_sha": sha, "source_ref": "main"}
    )
    record_receipt(ticket, evidence, body, owner_id=11)
    record_receipt(ticket, evidence, running(body), owner_id=11)
    complete_delivery_if_ready(ticket, evidence)
    assert ticket.status == "processing"
    employee = {
        **body,
        "artifact_id": "wrapped-employee",
        "receipt_token": "second-grant",
        "receipt_id": "employee-installed",
    }
    record_receipt(ticket, evidence, employee, owner_id=11)
    complete_delivery_if_ready(ticket, evidence)
    assert ticket.status == "processing"
    record_receipt(
        ticket, evidence, {**running(employee), "receipt_id": "employee-running"}, owner_id=11
    )
    complete_delivery_if_ready(ticket, evidence)
    assert ticket.status == "resolved"


def test_install_is_not_complete_and_retry_can_verify_release(receipt_case, monkeypatch):
    from modstore_server import customer_delivery_receipts as receipts
    from modstore_server.customer_service_delivery_completion import (
        complete_delivery_if_ready,
    )

    ticket, evidence, body = receipt_case
    record_receipt(ticket, evidence, body, owner_id=11)
    assert record_receipt(ticket, evidence, body, owner_id=11)["replayed"]
    complete_delivery_if_ready(ticket, evidence)
    assert ticket.status == "processing"
    monkeypatch.setattr(receipts, "trusted_host_release", lambda sha: None)
    assert not record_receipt(ticket, evidence, running(body), owner_id=11)["record"]["verified"]
    complete_delivery_if_ready(ticket, evidence)
    assert ticket.status == "processing"
    monkeypatch.setattr(
        receipts,
        "trusted_host_release",
        lambda sha: {"git_sha": sha, "source_ref": "main", "artifact_sha256": "d" * 64},
    )
    assert record_receipt(ticket, evidence, running(body), owner_id=11)["record"]["verified"]
    assert len(evidence["receipt_events"]) == 2
    complete_delivery_if_ready(ticket, evidence)
    assert ticket.status == "resolved"


@pytest.mark.parametrize(
    "field,value",
    [
        ("package_sha256", "e" * 64),
        ("installed_version", "1.0.0"),
        ("artifact_id", "other"),
        ("receipt_token", "other-token-fixture"),
        ("client_instance_id", ""),
    ],
)
def test_wrong_package_rejected(receipt_case, field, value):
    ticket, evidence, body = receipt_case
    body[field] = value
    with pytest.raises(HTTPException):
        record_receipt(ticket, evidence, body, owner_id=11)
    assert not evidence.get("receipt_events")


def test_owner_and_install_order_and_receipt_identity(receipt_case):
    ticket, evidence, body = receipt_case
    with pytest.raises(HTTPException):
        record_receipt(ticket, evidence, body, owner_id=12)
    with pytest.raises(HTTPException):
        record_receipt(ticket, evidence, running(body), owner_id=11)
    record_receipt(ticket, evidence, body, owner_id=11)
    with pytest.raises(HTTPException):
        record_receipt(ticket, evidence, dict(body, host="changed"), owner_id=11)


@pytest.mark.parametrize("change", ["case", "evidence", "files", "client", "generation"])
def test_runtime_exact_case_client_files_generation(receipt_case, change):
    ticket, evidence, body = receipt_case
    record_receipt(ticket, evidence, body, owner_id=11)
    value = running(body)
    if change == "case":
        value["business_verification"]["case_id"] = "other-case"
    elif change == "evidence":
        value["business_verification"]["observations"] = {}
    elif change == "files":
        value["runtime_files_sha256"] = "e" * 64
    elif change == "client":
        value["client_instance_id"] = "other-client"
    else:
        evidence["delivery_generation"] = "new-run"
    with pytest.raises(HTTPException):
        record_receipt(ticket, evidence, value, owner_id=11)


def test_intake_owner_bound_atomic_idempotent(client):
    from modstore_server.api.deps import get_current_user
    from modstore_server.app import app
    from modstore_server.models import OutboxEvent, UserMod, get_session_factory
    from modstore_server.models_cs import CustomerServiceTicket
    from tests.test_customer_service_api import _make_user

    sf = get_session_factory()
    owner = _make_user("private-intake")
    with sf() as db:
        db.add(UserMod(user_id=owner.id, mod_id="private-entitlement"))
        db.commit()
    app.dependency_overrides[get_current_user] = lambda: owner
    body = {
        "source": "private_mod_rework",
        "source_ref": uuid.uuid4().hex,
        "title": "Private issue",
        "description": "Original broken customer feature",
        "issue_domain": "custom",
        "target_mod_id": "private-entitlement",
        "installed_version": "1.0",
    }
    try:
        first = client.post("/api/customer-service/issues/intake", json=body)
        assert first.status_code == 200, first.text
        data = first.json()
        again = client.post("/api/customer-service/issues/intake", json=body)
        assert again.json()["ticket_id"] == data["ticket_id"] and again.json()["replayed"]
        assert (
            client.post(
                "/api/customer-service/issues/intake",
                json={**body, "description": "different issue"},
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/customer-service/issues/intake",
                json={**body, "target_mod_id": "not-owned"},
            ).status_code
            == 403
        )
        with sf() as db:
            row = db.get(CustomerServiceTicket, data["ticket_id"])
            ev = json.loads(row.evidence_json)
            assert (
                ev["resolution"]["owner_user_id"] == owner.id
                and ev["resolution"]["route"] == "private_mod"
            )
            assert ev["resolution"]["original_request"] == body["description"]
            events = (
                db.query(OutboxEvent)
                .filter(OutboxEvent.aggregate_id.like(row.ticket_no + ":%"))
                .all()
            )
            assert len(events) == 1 and events[0].status == "pending"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.parametrize("incident_state", ["truncated", "identity_erased", "healthy"])
def test_customer_feedback_keeps_work_order_and_verified_bundle_in_owner_event(
    client, monkeypatch, incident_state
):
    from modstore_server import customer_service_api
    from modstore_server.auth_service import create_access_token
    from modstore_server.db.ops_events import OutboxEvent
    from modstore_server.db.work_orders import WorkOrderEvent
    from modstore_server.models import IncidentEvent, get_session_factory
    from modstore_server.models_cs import CustomerServiceTicket
    from tests.test_customer_service_api import _make_user

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("manifest.json", '{"redacted":true}')
    raw = archive.getvalue()
    sha = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(
        customer_service_api,
        "_schedule_customer_ticket_incident",
        lambda _payload: None,
    )
    sf = get_session_factory()
    user = _make_user("feedback")
    headers = {"Authorization": f"Bearer {create_access_token(user.id, user.username)}"}
    candidate = client.post(
        "/api/work-orders/customer-candidate",
        json={
            "dedup_key": "customer-report-1",
            "reason": "product_defect",
            "expected": "save succeeds",
            "actual": "save fails",
            "confidence": 0.95,
            "support_bundle_sha256": sha,
            "client_instance_id": "test-instance",
            "product_version": "1.0.0.5",
            "git_sha": "a" * 40,
            "platform": "macOS",
        },
        headers=headers,
    )
    wo_id = candidate.json()["wo_id"]
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("manifest.json", '{"redacted":true,"retry":true}')
        bundle.writestr("logs/backend.log", "X" * 45000)
    raw = archive.getvalue()
    sha = hashlib.sha256(raw).hexdigest()
    body = {
        "source": "customer_feedback",
        "source_ref": wo_id,
        "title": "Client defect",
        "description": "The client action returns an error instead of saving.",
        "issue_domain": "platform",
        "work_order_id": wo_id,
        "support_bundle_sha256": sha,
        "support_bundle_base64": base64.b64encode(raw).decode("ascii"),
    }
    first = client.post("/api/customer-service/issues/intake", json=body, headers=headers)
    assert first.status_code == 200, first.text
    replay = client.post("/api/customer-service/issues/intake", json=body, headers=headers)
    assert replay.json()["ticket_id"] == first.json()["ticket_id"] and replay.json()["replayed"]
    with sf() as db:
        ticket = db.get(CustomerServiceTicket, first.json()["ticket_id"])
        evidence = json.loads(ticket.evidence_json)
        assert evidence["work_order_id"] == wo_id
        assert evidence["support_bundle_sha256"] == sha
        assert base64.b64decode(evidence["support_bundle_base64"]) == raw
        events = (
            db.query(OutboxEvent)
            .filter(OutboxEvent.aggregate_id.like(ticket.ticket_no + ":%"))
            .all()
        )
        assert len(events) == 1
        payload = json.loads(events[0].payload_json)
        assert [payload["work_order_id"], payload["support_bundle_sha256"]] == [wo_id, sha]
        assert base64.b64decode(payload["support_bundle_base64"]) == raw
        wo_events = (
            db.query(WorkOrderEvent).filter_by(wo_id=wo_id).order_by(WorkOrderEvent.id).all()
        )
        assert any(
            event.event == "transition" and event.to_state == "routed" for event in wo_events
        )
        receipts = [json.loads(event.ref or "{}") for event in wo_events if event.event == "gate"]
        assert {item.get("gate_status") for item in receipts} == {"ROUTED", "COLLECTED"}
    from modstore_server import incident_bus

    original = (
        json.dumps(payload)
        if incident_state == "healthy"
        else (json.dumps(payload)[:8000] if incident_state == "truncated" else '{"_team_claim":{}}')
    )
    original_outbox = ("dispatched", "original failure", 7)
    with sf() as db:
        outbox = db.get(OutboxEvent, events[0].id)
        outbox.status, outbox.last_error, outbox.attempts = original_outbox
        incident = IncidentEvent(
            event_type="ops.intake.customer_ticket",
            source="customer-issue-intake",
            fingerprint=hashlib.sha256(outbox.event_id.encode()).hexdigest(),
            payload_json=original,
        )
        db.add(incident)
        db.commit()
        original_id, outbox_id = incident.id, outbox.id
    calls = []
    monkeypatch.setenv("MODSTORE_INCIDENT_SYNC_DISPATCH", "1")
    monkeypatch.setattr(incident_bus, "_dispatch_incident", calls.append)
    monkeypatch.setattr(incident_bus, "_publish_stream_shadow", lambda *a, **k: None)
    monkeypatch.setattr(
        customer_service_api,
        "_schedule_customer_ticket_incident",
        customer_service_api._publish_customer_ticket_incident,
    )
    for _ in range(2):
        retry = client.post("/api/customer-service/issues/intake", json=body, headers=headers)
        assert retry.status_code == 200 and retry.json()["ticket_id"] == ticket.id
    other = _make_user("other-feedback")
    denied = client.post(
        "/api/customer-service/issues/intake",
        json=body,
        headers={"Authorization": f"Bearer {create_access_token(other.id, other.username)}"},
    )
    assert denied.status_code == 409
    with sf() as db:
        restored = (
            db.query(IncidentEvent)
            .filter_by(fingerprint=incident.fingerprint)
            .order_by(IncidentEvent.id)
            .all()
        )
        assert len(restored) == (1 if incident_state == "healthy" else 2)
        assert db.get(IncidentEvent, original_id).payload_json == original
        replay_payload = json.loads(restored[-1].payload_json)
        assert all(
            replay_payload[k] == payload[k]
            for k in ("ticket_id", "user_id", "ticket_no", "work_order_id", "support_bundle_base64")
        )
        if incident_state != "healthy":
            assert replay_payload["_incident_replay"] == {
                "original_event_id": original_id,
                "original_payload_sha256": hashlib.sha256(original.encode()).hexdigest(),
            }
        outbox = db.get(OutboxEvent, outbox_id)
        assert (outbox.status, outbox.last_error, outbox.attempts) == original_outbox
        assert calls == ([] if incident_state == "healthy" else [restored[-1].id])
    marker = f"unpersisted-{uuid.uuid4().hex}"
    body.update(source_ref="bad-work-order", title=marker, work_order_id="WO-111111111111")
    bad = client.post("/api/customer-service/issues/intake", json=body, headers=headers)
    assert bad.status_code == 409
    with sf() as db:
        assert not db.query(CustomerServiceTicket).filter_by(title=marker).first()


def test_unknown_host_failure_stays_pending_and_same_id_can_be_verified(receipt_case, monkeypatch):
    from modstore_server import customer_delivery_receipts as receipts

    ticket, evidence, body = receipt_case
    record_receipt(ticket, evidence, body, owner_id=11)
    failed = running(body)
    probe = failed["business_verification"]
    probe["passed"] = False
    probe["evidence_sha256"] = canonical_sha256(
        {key: probe[key] for key in ("case_id", "passed", "observations", "observed_at")}
    )
    failed.update(stage="verification_failed", receipt_id="failed-probe")
    monkeypatch.setattr(receipts, "trusted_host_release", lambda sha: None)
    first = record_receipt(ticket, evidence, failed, owner_id=11)
    assert first["record"]["failure_recorded"] is False
    assert first["record"]["verified"] is False
    monkeypatch.setattr(
        receipts, "trusted_host_release", lambda sha: {"git_sha": sha, "source_ref": "main"}
    )
    second = record_receipt(ticket, evidence, failed, owner_id=11)
    assert second["record"]["failure_recorded"] is True and second["record"]["verified"] is False
    assert len(evidence["receipt_events"]) == 2
    assert record_receipt(ticket, evidence, failed, owner_id=11)["replayed"] is True


def test_same_work_order_support_reports_are_durable(client, auth_headers, monkeypatch):
    from modstore_server import customer_service_api
    from modstore_server.models import OutboxEvent, get_session_factory
    from modstore_server.models_cs import CustomerServiceTicket

    monkeypatch.setattr(customer_service_api, "_schedule_customer_ticket_incident", lambda _: None)
    bundles = []
    for version in range(2):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("manifest.json", json.dumps({"synthetic": version}))
        raw = stream.getvalue()
        bundles.append(
            {
                "support_bundle_sha256": hashlib.sha256(raw).hexdigest(),
                "support_bundle_base64": base64.b64encode(raw).decode(),
            }
        )
    candidate = client.post(
        "/api/work-orders/customer-candidate",
        headers=auth_headers,
        json={
            "dedup_key": uuid.uuid4().hex,
            "reason": "product_defect",
            "expected": "saves",
            "actual": "fails",
            "confidence": 0.95,
            **{k: v for k, v in bundles[0].items() if k.endswith("sha256")},
            "client_instance_id": "original",
            "product_version": "1.0.0.4",
            "git_sha": "a" * 40,
            "platform": "Windows",
        },
    )
    wo = candidate.json()["wo_id"]
    body = {
        "source": "customer_feedback",
        "source_ref": wo,
        "work_order_id": wo,
        "title": "Synthetic repeat",
        "description": "Same original failure",
        **bundles[0],
    }
    first = client.post("/api/customer-service/issues/intake", json=body, headers=auth_headers)
    assert first.status_code == 200, first.text
    for metadata in (
        {},
        {"customer_instance_id": "mac", "product_version": "1.0.0.5", "git_sha": "b" * 40},
    ):
        supplement = {**body, **bundles[1], **metadata}
        for _ in range(2):
            result = client.post(
                "/api/customer-service/issues/intake", json=supplement, headers=auth_headers
            )
            assert result.status_code == 200, result.text
            assert result.json()["ticket_id"] == first.json()["ticket_id"]
            assert (
                result.json()["support_bundle_saved"]
                and result.json()["support_bundle_sha256"] == bundles[1]["support_bundle_sha256"]
            )
    assert (
        client.post(
            "/api/customer-service/issues/intake",
            headers=auth_headers,
            json={**supplement, "description": "A different failure"},
        ).status_code
        == 409
    )
    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, first.json()["ticket_id"])
        evidence = json.loads(ticket.evidence_json)
        assert all(evidence[key] == value for key, value in bundles[0].items())
        reports = evidence["support_reports"]
        assert len(reports) == 2 and reports[-1]["customer_instance_id"] == "mac"
        assert all(all(row[key] == value for key, value in bundles[1].items()) for row in reports)
        events = (
            db.query(OutboxEvent)
            .filter(OutboxEvent.aggregate_id.like(ticket.ticket_no + ":%"))
            .order_by(OutboxEvent.id)
            .all()
        )
        assert len(events) == 3
        payloads = [json.loads(row.payload_json) for row in events]
        assert payloads[0]["support_bundle_sha256"] == bundles[0]["support_bundle_sha256"]
        assert all(
            row["ticket_id"] == ticket.id
            and row["work_order_id"] == wo
            and all(row[key] == value for key, value in bundles[1].items())
            for row in payloads[1:]
        )
        ticket.status = "closed"
        db.commit()
    assert (
        client.post(
            "/api/customer-service/issues/intake",
            headers=auth_headers,
            json={**supplement, "customer_instance_id": "another"},
        ).status_code
        == 409
    )
