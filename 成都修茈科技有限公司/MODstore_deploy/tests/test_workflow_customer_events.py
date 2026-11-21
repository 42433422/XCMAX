"""Private execution contracts stay in SQL across actual outbox publish/replay paths."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from modstore_server import models, webhook_dispatcher
from modstore_server.api import admin_events
from modstore_server.eventing import db_outbox


@pytest.fixture
def private_outbox(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "outbox.sqlite"))
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(models, "_engine", engine)
    monkeypatch.setattr(models, "_SessionFactory", factory)
    app = FastAPI()
    app.include_router(admin_events.router)

    def database():
        with factory() as session:
            yield session

    app.dependency_overrides[admin_events.get_db] = database
    app.dependency_overrides[admin_events._get_current_user] = lambda: SimpleNamespace(
        is_admin=True
    )
    with TestClient(app) as http:
        yield factory, http
    engine.dispose()


@pytest.mark.parametrize(
    "event_name",
    [
        "workflow.execution.feedback_started",
        "workflow.customer.delivery_started",
        "workflow.customer.delivery_produced",
    ],
)
def test_real_dispatch_bus_dlq_and_admin_replay_only_publish_fixed_public_projection(
    private_outbox, monkeypatch, event_name
):
    factory, http = private_outbox
    public = {
        "execution_id": 31,
        "workflow_id": 9,
        "user_id": 4,
        "node_id": 17,
        "contract_sha256": "c" * 64,
    }
    private = {
        **public,
        "customer_delivery": {
            "input_data": {"customer_input": "private-customer-order"},
            "execution_binding": {"workspace_root": "/private/tenant/workspace"},
            "policy": {"internal_only": True},
        },
        "artifacts": [{"output_path": "outputs/private-customer-order.csv"}],
        "public_payload": {"customer_input": "private-customer-order"},
        "redact": False,  # No payload-controlled switch can broaden the fixed projection.
    }
    with factory() as db:
        db_outbox.enqueue(db, event_name, "private-workflow", private)
        db.commit()
    record = db_outbox.fetch_pending()[0]
    assert record.payload == private
    assert record.to_envelope()["data"] == public
    assert record.to_domain_event().payload == public
    envelopes, events = [], []

    class Bus:
        def publish(self, event):
            events.append(event.to_dict())

    def unavailable(envelope):
        envelopes.append(envelope)
        return {"ok": False, "message": "Synthetic receiver unavailable"}

    monkeypatch.setattr(db_outbox, "neuro_bus", Bus())
    monkeypatch.setattr(webhook_dispatcher, "dispatch_event", unavailable)
    monkeypatch.setenv("MODSTORE_OUTBOX_MAX_ATTEMPTS", "1")
    assert db_outbox.drain() == {"sent": 0, "failed": 1, "skipped": 0}
    assert envelopes[0]["data"] == public and events[0]["payload"] == public
    # The existing administrator read API exposes metadata, never the SQL contract.
    dlq = http.get("/api/admin/events/dlq")
    assert dlq.status_code == 200 and dlq.json()["unresolved_count"] == 1
    assert "private-customer-order" not in dlq.text and "payload_json" not in dlq.text

    def deliver(envelope):
        envelopes.append(envelope)
        return {"ok": True}

    monkeypatch.setattr(webhook_dispatcher, "dispatch_event", deliver)
    replay = http.post("/api/admin/events/replay", params={"event_id": record.event_id})
    assert replay.status_code == 200 and replay.json()["reset"] == 1
    assert envelopes[-1]["data"] == public and events[-1]["payload"] == public
    assert "private-customer-order" not in json.dumps(envelopes + events)
    with factory() as db:
        row = db.scalar(select(models.OutboxEvent).where(models.OutboxEvent.id == record.id))
        assert row.status == "dispatched" and json.loads(row.payload_json) == private
        assert json.loads(db.scalar(select(models.OutboxDeadLetter)).payload_json) == private


def test_unrelated_outbox_payload_remains_compatible(private_outbox):
    factory, _http = private_outbox
    payload = {"out_trade_no": "synthetic-order", "user_id": 4, "total_amount": "1.00"}
    with factory() as db:
        db_outbox.enqueue(db, "payment.paid", "synthetic-order", payload)
        db.commit()
    record = db_outbox.fetch_pending()[0]
    assert record.to_envelope()["data"] == payload
    assert record.to_domain_event().payload == payload
