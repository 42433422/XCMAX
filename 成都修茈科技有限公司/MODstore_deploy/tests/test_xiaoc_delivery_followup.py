"""Management follow-ups use owned delivery facts and one in-app cursor."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modstore_server.api.deps import get_current_user, get_db
from modstore_server.customer_service_human_api import router as human_router
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
    app.include_router(human_router, prefix="/api/customer-service")
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
    client, sessions, identity = delivery
    with sessions() as db:
        db.get(CustomerServiceTicket, 21).title = "客户私有问题描述"
        db.commit()
    request = {"change": "delivery-change", "reason": "记录已确认的交付检查项"}
    requested = client.post("/api/customer-service/tickets/21/sensitive-action", json=request)
    assert requested.status_code == 200
    assert requested.json()["status"] == "waiting_approval"
    action_id = str(requested.json()["action_id"])
    path = f"{PATH}/21"
    assert client.get(path).json()["item"]["approval_id"] is None  # Same person cannot approve.
    assert client.post(f"{path}/approve", json={"approval_id": action_id}).status_code == 409

    identity["user_id"] = 2
    assert {row["ticket_id"] for row in client.get(PATH).json()["items"]} == {21, 22}
    detail = client.get(path)
    assert detail.status_code == 200
    assert detail.json()["events"] == []
    assert "客户私有问题描述" not in detail.text
    item = detail.json()["item"]
    assert item["can_follow"] is False
    assert item["can_resume"] is False
    assert item["approval_id"] == action_id
    assert item["approval_title"] == "delivery-change"
    assert item["approval_reason"] == request["reason"]
    assert client.put(path, json={"following": True}).status_code == 404
    assert client.post(f"{path}/resume").status_code == 404
    assert client.get(f"{PATH}/23").status_code == 404
    assert client.post(f"{path}/approve", json={"approval_id": "99999"}).status_code == 409
    response = client.post(f"{path}/approve", json={"approval_id": action_id})
    assert response.status_code == 200
    assert response.json()["events"] == []
    assert response.json()["item"]["approval_id"] is None
    assert client.get(path).status_code == 404
    assert [row["ticket_id"] for row in client.get(PATH).json()["items"]] == [22]
    assert client.post(f"{path}/approve", json={"approval_id": action_id}).status_code == 404
    with sessions() as db:
        assert db.get(CustomerServiceAction, int(action_id)).status == "pending_execution"
        assert db.get(CustomerServiceTicket, 21).assigned_admin_id == 1
        assert db.get(XiaoCDeliveryFollowup, (2, 21)) is None


@pytest.mark.parametrize("explicit_generation", [True, False])
def test_current_production_failure_notifies_once_from_persisted_session(
    delivery, monkeypatch, tmp_path, explicit_generation
):
    from modstore_server import workbench_api

    client, sessions, _ = delivery
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(workbench_api, "WORKBENCH_SESSIONS", {})
    monkeypatch.setattr(workbench_api, "_SESSION_LOCK", asyncio.Lock())
    current, previous = "c" * 32, "a" * 32
    for sid in (previous, current):
        workbench_api.WORKBENCH_SESSIONS[sid] = {
            "id": sid,
            "user_id": 3,
            "ticket_id": 21,
            "intent": "module",
            "status": "running",
            "artifact": None,
            "steps": [{"id": "mod_sandbox", "status": "running"}],
            "source_scope": {"owner_user_id": 3, "session_id": sid, "ticket_id": 21},
        }
        workbench_api._persist_workbench_session_unlocked(sid)
    runs = [{"session_id": sid, "status": "running"} for sid in (previous, current)]
    evidence = {"runs": list(reversed(runs)) if explicit_generation else runs}
    if explicit_generation:
        evidence["delivery_generation"] = current
    with sessions() as db:
        db.get(CustomerServiceTicket, 21).evidence_json = json_dumps(evidence)
        db.commit()
    now = datetime.now(UTC)
    path = f"{PATH}/21"
    assert client.put(path, json={"following": True}).status_code == 200

    asyncio.run(workbench_api._fail_session(previous, "mod_sandbox", "旧生产失败"))
    with sessions() as db:
        check_delivery_followups(db, now=now + timedelta(minutes=6))
        assert db.query(Notification).count() == 0
    assert client.get(path).json()["item"]["stage"] == "production"

    asyncio.run(workbench_api._fail_session(current, "mod_sandbox", "当前生产私有错误详情"))
    # Another worker may still hold a running snapshot; the persisted failure is authoritative.
    workbench_api.WORKBENCH_SESSIONS[current]["status"] = "running"
    with sessions() as db:
        ticket = db.get(CustomerServiceTicket, 21)
        assert ticket.status == "processing"
        assert ticket.evidence_json == json_dumps(evidence)
        check_delivery_followups(db, now=now + timedelta(minutes=12))
        check_delivery_followups(db, now=now + timedelta(minutes=18))
        notice = db.query(Notification).one()
        assert notice.user_id == 1
        assert "返工" in notice.content
        assert "私有错误详情" not in notice.content
    item = client.get(path).json()["item"]
    assert item["needs_attention"] is True
    assert "返工" in item["attention_reason"]
    assert item["stage"] == "rework"
    assert "返工" in item["stage_label"]


@pytest.mark.parametrize("invalid_field", ["user_id", "ticket_id", "source_scope"])
def test_unowned_production_snapshot_cannot_trigger_a_failure_notice(
    delivery, monkeypatch, tmp_path, invalid_field
):
    from modstore_server import workbench_api

    client, sessions, _ = delivery
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(workbench_api, "WORKBENCH_SESSIONS", {})
    monkeypatch.setattr(workbench_api, "_SESSION_LOCK", asyncio.Lock())
    sid = "d" * 32
    snapshot = {
        "id": sid,
        "user_id": 3,
        "ticket_id": 21,
        "status": "running",
        "steps": [],
        "source_scope": {"owner_user_id": 3, "session_id": sid, "ticket_id": 21},
    }
    snapshot[invalid_field] = (
        {"owner_user_id": 3, "session_id": "a" * 32, "ticket_id": 21}
        if invalid_field == "source_scope"
        else 999
    )
    workbench_api.WORKBENCH_SESSIONS[sid] = snapshot
    workbench_api._persist_workbench_session_unlocked(sid)
    with sessions() as db:
        db.get(CustomerServiceTicket, 21).evidence_json = json_dumps(
            {"delivery_generation": sid, "runs": [{"session_id": sid}]}
        )
        db.commit()
    now = datetime.now(UTC)
    assert client.put(f"{PATH}/21", json={"following": True}).status_code == 200
    asyncio.run(workbench_api._fail_session(sid, "mod_sandbox", "不属于当前工单的私有错误"))
    with sessions() as db:
        check_delivery_followups(db, now=now + timedelta(minutes=6))
        assert db.query(Notification).count() == 0
    detail = client.get(f"{PATH}/21").json()
    assert detail["item"]["needs_attention"] is False
    assert "私有错误" not in str(detail)


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
