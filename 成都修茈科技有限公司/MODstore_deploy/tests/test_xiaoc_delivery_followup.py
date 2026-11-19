"""Management follow-ups use owned delivery facts and one in-app cursor."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modstore_server.api.deps import get_current_user, get_db
from modstore_server.customer_service_tools import json_dumps
from modstore_server.models import Base, Notification, User
from modstore_server.models_cs import (
    CustomerServiceAction,
    CustomerServiceSession,
    CustomerServiceTicket,
    XiaoCDeliveryFollowup,
)
from modstore_server.xiaoc_delivery_followup import check_delivery_followups
from modstore_server.xiaoc_delivery_followup_api import router

PATH = "/api/agent/butler/delivery-followups"


@pytest.fixture
def delivery(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'delivery.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add_all(
            [
                User(id=1, username="admin-1", password_hash="x", is_admin=True),
                User(id=2, username="admin-2", password_hash="x", is_admin=True),
                User(id=3, username="client", password_hash="x", is_admin=False),
            ]
        )
        db.flush()
        db.add_all(
            [
                CustomerServiceSession(id=10, user_id=3),
                CustomerServiceSession(id=11, user_id=2),
            ]
        )
        db.flush()
        db.add_all(
            [
                CustomerServiceTicket(
                    id=21,
                    session_id=10,
                    user_id=3,
                    assigned_admin_id=1,
                    intent="custom_delivery",
                    ticket_no="D-21",
                    status="processing",
                ),
                CustomerServiceTicket(
                    id=22,
                    session_id=11,
                    user_id=2,
                    intent="custom_delivery",
                    ticket_no="D-22",
                ),
                CustomerServiceTicket(
                    id=23,
                    session_id=10,
                    user_id=3,
                    assigned_admin_id=1,
                    intent="refund",
                    ticket_no="R-23",
                ),
            ]
        )
        db.commit()

    app = FastAPI()
    app.include_router(router)
    identity = {"user_id": 1}

    def fake_login():
        with sessions() as db:
            return db.get(User, identity["user_id"])

    def test_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_current_user] = fake_login
    app.dependency_overrides[get_db] = test_db
    with TestClient(app) as client:
        yield client, sessions, identity
    engine.dispose()


def test_only_assigned_or_owned_delivery_is_visible_and_mutable(delivery):
    client, sessions, identity = delivery
    assert [row["ticket_id"] for row in client.get(PATH).json()["items"]] == [21]
    assert client.get(f"{PATH}/22").status_code == 404
    assert client.get(f"{PATH}/23").status_code == 404
    assert client.put(f"{PATH}/22", json={"following": True}).status_code == 404
    assert client.post(f"{PATH}/22/resume").status_code == 404
    reply = client.put(f"{PATH}/21", json={"following": True})
    assert reply.status_code == 200
    assert reply.json()["item"]["following"] is True
    assert reply.json()["item"]["expected_completion_at"] is None
    with sessions() as db:
        assert db.get(XiaoCDeliveryFollowup, (1, 21)).following

    identity["user_id"] = 2
    assert [row["ticket_id"] for row in client.get(PATH).json()["items"]] == [22]
    assert client.get(f"{PATH}/21").status_code == 404
    identity["user_id"] = 3
    assert client.get(PATH).status_code == 403


def test_scheduler_only_notifies_on_change_and_stops_on_pause_or_scope_loss(delivery):
    client, sessions, _ = delivery
    now = datetime.now(UTC)
    with sessions() as db:
        ticket = db.get(CustomerServiceTicket, 21)
        ticket.expected_completion_at = now + timedelta(minutes=20)
        db.commit()
    assert client.put(f"{PATH}/21", json={"following": True}).status_code == 200
    with sessions() as db:
        check_delivery_followups(db, now=now + timedelta(minutes=10))
        assert db.query(Notification).count() == 0
        check_delivery_followups(db, now=now + timedelta(minutes=21))
        check_delivery_followups(db, now=now + timedelta(minutes=31))
        notice = db.query(Notification).one()
        assert notice.user_id == 1
        assert "预计完成时间" in notice.content

    assert client.put(f"{PATH}/21", json={"following": False}).status_code == 200
    with sessions() as db:
        db.get(CustomerServiceTicket, 21).status = "waiting_approval"
        db.commit()
        check_delivery_followups(db, now=now + timedelta(minutes=42))
        assert db.query(Notification).count() == 1

    assert client.put(f"{PATH}/21", json={"following": True}).status_code == 200
    with sessions() as db:
        db.get(CustomerServiceTicket, 21).assigned_admin_id = 2
        db.commit()
        check_delivery_followups(db, now=now + timedelta(minutes=50))
        assert db.query(Notification).count() == 1
        assert not db.get(XiaoCDeliveryFollowup, (1, 21)).following


def test_approval_is_bound_to_a_real_request_and_is_not_execution(delivery):
    client, sessions, _ = delivery
    request = {"change": "delivery-change", "reason": "记录已确认的交付检查项"}
    with sessions() as db:
        action = CustomerServiceAction(
            ticket_id=21,
            user_id=1,
            action_type="ticket.apply_change",
            status="waiting_approval",
            request_json=json_dumps(request),
            idempotency_key="delivery-gated",
        )
        db.add(action)
        db.commit()
        action_id = str(action.id)
    path = f"{PATH}/21"
    assert client.get(path).json()["item"]["approval_id"] is None  # Same person cannot approve.
    assert client.post(f"{path}/approve", json={"approval_id": action_id}).status_code == 409
    with sessions() as db:
        db.get(CustomerServiceAction, int(action_id)).user_id = 2
        db.commit()

    item = client.get(path).json()["item"]
    assert item["approval_id"] == action_id
    assert item["approval_title"] == "delivery-change"
    assert item["approval_reason"] == request["reason"]
    response = client.post(f"{path}/approve", json={"approval_id": action_id})
    assert response.status_code == 200
    events = response.json()["events"]
    assert any(event["status"] == "pending_execution" for event in events)
    assert response.json()["item"]["approval_id"] is None
    assert client.post(f"{path}/approve", json={"approval_id": action_id}).status_code == 409
    with sessions() as db:
        assert db.get(CustomerServiceAction, int(action_id)).status == "pending_execution"


def test_closed_ticket_needs_current_generation_runtime_receipt_to_display_delivered(
    delivery,
):
    client, sessions, _ = delivery
    artifact = {
        "kind": "module",
        "id": "mod-1",
        "version": "1",
        "package_sha256": "a" * 64,
    }
    receipt = {
        **artifact,
        "receipt_id": "runtime-1",
        "received_at": datetime.now(UTC).isoformat(),
        "generation": "prior",
        "owner_user_id": 3,
        "client_instance_id": "customer-desktop",
        "stage": "running",
        "verified": True,
    }
    evidence = {
        "delivery_artifacts": [artifact],
        "delivery_generation": "current",
        "delivered_at": receipt["received_at"],
        "acceptance_status": "accepted",
        "resolution": {"repair_verified_by": "delivery_runtime_receipt"},
        "receipt_events": [receipt],
    }
    path = f"{PATH}/21"
    with sessions() as db:
        ticket = db.get(CustomerServiceTicket, 21)
        ticket.status = "resolved"
        ticket.evidence_json = json_dumps(evidence)
        db.commit()
    payload = client.get(path).json()
    assert payload["item"]["stage"] == "closed"
    assert not any(row["id"] == "delivered" for row in payload["events"])

    with sessions() as db:
        receipt["generation"] = "current"
        db.get(CustomerServiceTicket, 21).evidence_json = json_dumps(evidence)
        db.commit()
    payload = client.get(path).json()
    assert payload["item"]["stage"] == "delivered"
    assert any(row["id"] == "delivered" for row in payload["events"])
