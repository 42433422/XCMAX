"""Confirmed public repair reuse remains separate from each customer's acceptance."""

import uuid

import pytest

from modstore_server.customer_service_tools import json_dumps, json_loads
from tests.test_customer_issue_delivery_pipeline import github_fixture, make_ticket, seed_repair


def _as(monkeypatch, user):
    from modstore_server.api.deps import get_current_user
    from modstore_server.app import app

    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: user)


@pytest.fixture
def pair(client, monkeypatch):
    from modstore_server.models import get_session_factory
    from modstore_server.models_cs import CustomerServiceTicket
    from tests.test_customer_service_api import _make_user

    monkeypatch.setattr("modstore_server.customer_issue_api._wake_owner_intake", lambda *args: None)
    source_user, source_id = make_ticket(client, monkeypatch)
    target_user, target_id = make_ticket(client, monkeypatch)
    with get_session_factory()() as db:
        for tid in (source_id, target_id):
            ticket = db.get(CustomerServiceTicket, tid)
            evidence = json_loads(ticket.evidence_json, {})
            evidence.update(git_sha="1" * 40, product_version="1.0.0")
            ticket.evidence_json = json_dumps(evidence)
        seed_repair(db, db.get(CustomerServiceTicket, source_id))
    admin = _make_user("reuse_admin", admin=True)
    _as(monkeypatch, admin)
    response = client.get(f"/api/customer-service/issues/{target_id}/shared-repair-candidates")
    assert response.status_code == 200, response.text
    candidate = next(
        row for row in response.json()["items"] if row["source_ticket_id"] == source_id
    )
    body = {
        "source_ticket_id": source_id,
        "source_action_id": candidate["source_action_id"],
        "match_sha256": response.json()["match_sha256"],
        "confirmed_same_root_cause": True,
        "note": "已对照原版本复现，确认同根因且公共修复适用",
        "request_id": uuid.uuid4().hex,
    }
    return {
        "source_user": source_user,
        "target_user": target_user,
        "admin": admin,
        "source_id": source_id,
        "target_id": target_id,
        "body": body,
        "url": f"/api/customer-service/issues/{target_id}/shared-repair",
    }


def test_confirmed_link_skips_repeat_dispatch_and_keeps_customer_acceptance_independent(
    client, monkeypatch, pair
):
    from modstore_server.customer_issue_intake import dispatch_issue_event
    from modstore_server.customer_issue_shared_repairs import active_shared_repair
    from modstore_server.models import get_session_factory
    from modstore_server.models_cs import CustomerServiceAction, CustomerServiceTicket

    linked = client.post(pair["url"], json=pair["body"])
    assert linked.status_code == 200, linked.text
    assert linked.json()["link"]["source_action_id"] == pair["body"]["source_action_id"]
    assert client.post(pair["url"], json=pair["body"]).json()["replayed"] is True
    conflict = client.post(pair["url"], json={**pair["body"], "note": "同标识不能更换此处确认记录"})
    assert conflict.status_code == 409
    published = []
    monkeypatch.setattr(
        "modstore_server.incident_bus.publish", lambda *a, **k: published.append(a) or True
    )
    envelope = {
        "id": "public-repair-test",
        "data": {
            "ticket_id": pair["target_id"],
            "user_id": pair["target_user"].id,
        },
    }
    assert dispatch_issue_event(envelope)["reason"] == "shared_repair_reused"
    assert not published
    with get_session_factory()() as db:
        target = db.get(CustomerServiceTicket, pair["target_id"])
        assert target.status == "processing" and target.closed_at is None
        assert active_shared_repair(db, target)
        assert (
            db.query(CustomerServiceAction)
            .filter_by(ticket_id=target.id, action_type="issue.repair.shared")
            .count()
            == 1
        )
    github_fixture(monkeypatch)
    _as(monkeypatch, pair["target_user"])
    pending = client.get(
        "/api/customer-service/issues/pending-runtime", params={"host_sha": "c" * 40}
    )
    assert pending.status_code == 200, pending.text
    item = next(row for row in pending.json()["items"] if row["id"] == pair["target_id"])
    target = item["target"]
    assert item["ready"] is True and target["owner_user_id"] == pair["target_user"].id
    receipt = {
        key: target[key]
        for key in ("host_sha", "version", "release_id", "signed_metadata_sha256", "case_id")
    }
    receipt.update(
        receipt_id="reuse-customer-confirmation",
        client_instance_id="target-instance",
        customer_confirmed=True,
        confirmation_note="本人在目标版本复测原问题已解决",
    )
    url = f"/api/customer-service/issues/{pair['target_id']}/runtime-receipt"
    _as(monkeypatch, pair["source_user"])
    assert client.post(url, json=receipt).status_code == 404
    _as(monkeypatch, pair["target_user"])
    closed = client.post(url, json=receipt)
    assert closed.status_code == 200, closed.text
    assert client.post(url, json=receipt).json()["receipt"]["replayed"] is True
    with get_session_factory()() as db:
        assert db.get(CustomerServiceTicket, pair["target_id"]).status == "resolved"
        assert db.get(CustomerServiceTicket, pair["source_id"]).status == "processing"
    reopened = client.post(
        f"/api/customer-service/issues/{pair['target_id']}/decision",
        json={
            "decision": "reopen",
            "note": "重新复测还有同一问题",
            "idempotency_key": "reuse-reopen-1",
        },
    )
    assert reopened.status_code == 200, reopened.text
    with get_session_factory()() as db:
        assert active_shared_repair(db, db.get(CustomerServiceTicket, pair["target_id"])) is None
    assert dispatch_issue_event(envelope)["published"] is True


@pytest.mark.parametrize(
    "change", ["version", "sha", "description", "private", "source_reopened", "source_worker"]
)
def test_link_rechecks_source_applicability_and_repair_proof(client, monkeypatch, pair, change):
    from modstore_server.models import EmployeeChangeRequest, get_session_factory
    from modstore_server.models_cs import CustomerServiceAction, CustomerServiceTicket

    with get_session_factory()() as db:
        ticket = db.get(CustomerServiceTicket, pair["target_id"])
        evidence = json_loads(ticket.evidence_json, {})
        if change == "version":
            evidence["product_version"] = "2.0.0"
        elif change == "sha":
            evidence["git_sha"] = "2" * 40
        elif change == "description":
            ticket.summary = "标题相近但不同的真实问题"
        elif change == "private":
            evidence.update(source="private_mod_rework", target_mod_id="private-customer-mod")
        elif change == "source_reopened":
            source = db.get(CustomerServiceTicket, pair["source_id"])
            original = json_loads(source.evidence_json, {})
            original["resolution"].update(
                repair_verified=False, reopen_after_action_id=pair["body"]["source_action_id"]
            )
            source.evidence_json = json_dumps(original)
        else:
            action = db.get(CustomerServiceAction, pair["body"]["source_action_id"])
            db.get(EmployeeChangeRequest, int(action.target_id)).source_employee_id = (
                "another-worker"
            )
        ticket.evidence_json = json_dumps(evidence)
        db.commit()
    result = client.post(pair["url"], json=pair["body"])
    assert result.status_code == 409, result.text
    with get_session_factory()() as db:
        assert (
            db.query(CustomerServiceAction)
            .filter_by(ticket_id=pair["target_id"], action_type="issue.repair.shared")
            .count()
            == 0
        )


def test_customer_cannot_link_or_discover_other_customer_repair(client, monkeypatch, pair):
    _as(monkeypatch, pair["target_user"])
    assert client.get(pair["url"] + "-candidates").status_code == 403
    assert client.post(pair["url"], json=pair["body"]).status_code == 403


@pytest.mark.parametrize("state", ["planned", "dispatching", "pending", "manual_review"])
def test_durable_current_plan_prevents_parallel_repair_link(client, pair, state):
    from modstore_server.models import IncidentEvent, get_session_factory

    with get_session_factory()() as db:
        db.add(
            IncidentEvent(
                event_type="ops.intake.customer_ticket",
                source="test",
                payload_json=json_dumps(
                    {
                        "ticket_id": pair["target_id"],
                        "user_id": pair["target_user"].id,
                        "_team_claim": {
                            "schema_version": 2,
                            "team": [{"role": "scout", "status": state}],
                        },
                    }
                ),
                fingerprint=uuid.uuid4().hex,
            )
        )
        db.commit()
    result = client.post(pair["url"], json=pair["body"])
    assert result.status_code == 409, result.text


def test_confirmation_is_explicit_and_exact(client, pair):
    result = client.post(pair["url"], json={**pair["body"], "confirmed_same_root_cause": False})
    assert result.status_code == 422
    result = client.post(pair["url"], json={**pair["body"], "match_sha256": "a" * 64})
    assert result.status_code == 409
