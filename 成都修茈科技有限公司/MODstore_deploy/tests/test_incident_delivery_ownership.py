"""Crash/replay boundaries use real SQL identities rather than process-local sets."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from modstore_server import incident_bus as bus
from modstore_server import models
from modstore_server import node_coordinator as nc
from modstore_server.eventing import db_outbox


@pytest.fixture
def factory(tmp_path, monkeypatch):
    engine = sa.create_engine(
        f"sqlite:///{tmp_path / 'delivery.sqlite'}", connect_args={"timeout": 10}
    )
    models.Base.metadata.create_all(engine)
    sf = sessionmaker(bind=engine)
    for module in (bus, nc, db_outbox):
        monkeypatch.setattr(module, "get_session_factory", lambda: sf)
    monkeypatch.setattr(bus, "_publish_stream_shadow", lambda *a, **k: None)
    yield sf
    engine.dispose()


def _publish():
    return bus.publish(
        "ops.intake.customer_ticket",
        {"ticket_id": 42, "user_id": 7},
        source="customer-issue-intake",
        fingerprint="stable-fingerprint",
        inbox_key="stable-event",
    )


def test_concurrent_intake_creates_one_incident_and_one_inbox(factory, monkeypatch):
    monkeypatch.setattr(bus, "_schedule_incident", lambda _: None)
    barrier = Barrier(2)

    def publish():
        barrier.wait(timeout=5)
        return _publish()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: publish(), range(2)))
    assert sum(results) == 1
    with factory() as db:
        assert db.query(models.IncidentEvent).count() == 1
        assert db.query(models.IncidentInbox).count() == 1


def test_commit_before_schedule_crash_recovers_original_identity(factory, monkeypatch):
    def crash(_):
        raise RuntimeError("process interrupted after commit")

    monkeypatch.setattr(bus, "_schedule_incident", crash)
    with pytest.raises(RuntimeError):
        _publish()
    scheduled = []
    monkeypatch.setattr(bus, "_schedule_incident", scheduled.append)
    assert _publish() is False
    monkeypatch.setattr(bus, "_dispatch_incident", scheduled.append)
    from modstore_server.customer_issue_intake import recover_pending_incidents

    assert recover_pending_incidents() == 1
    assert len(scheduled) == 2 and scheduled[0] == scheduled[1]
    with factory() as db:
        assert db.query(models.IncidentEvent).count() == 1


def test_interrupted_body_is_held_for_reconcile_not_submitted_twice(factory, monkeypatch):
    with factory() as db:
        event = models.IncidentEvent(event_type="on_error", source="test")
        db.add(event)
        db.commit()
        eid = event.id
    calls, reconciled = [], []

    def interrupted(event_id):
        calls.append(event_id)
        raise RuntimeError("response lost after external acceptance")

    monkeypatch.setattr(bus, "_dispatch_incident_body", interrupted)
    monkeypatch.setattr(
        "modstore_server.incident_team_completion.reconcile_pending_teams",
        lambda **kw: reconciled.append(kw),
    )
    with pytest.raises(RuntimeError):
        bus._dispatch_incident(eid)
    bus._dispatch_incident(eid)
    assert calls == [eid] and reconciled == [{"event_id": eid}]
    with factory() as db:
        assert db.get(models.IncidentClaim, eid).dispatch_state == "unknown"


def test_completed_dispatch_body_is_not_replayed(factory, monkeypatch):
    with factory() as db:
        event = models.IncidentEvent(event_type="on_error", source="test")
        db.add(event)
        db.commit()
        eid = event.id
    calls = []
    monkeypatch.setattr(bus, "_dispatch_incident_body", calls.append)
    monkeypatch.setattr(
        "modstore_server.incident_team_completion.reconcile_pending_teams",
        lambda **kw: None,
    )
    bus._dispatch_incident(eid)
    bus._dispatch_incident(eid)
    assert calls == [eid]


def test_two_drainers_with_same_snapshot_send_once(factory, monkeypatch):
    with factory() as db:
        db_outbox.enqueue(db, "test.event", "stable", {})
        db.commit()
    records = db_outbox.fetch_pending()
    barrier = Barrier(2)

    def simultaneous_snapshot(**kwargs):
        barrier.wait(timeout=5)
        return records

    monkeypatch.setattr(db_outbox, "fetch_pending", simultaneous_snapshot)
    calls = []

    def dispatch(envelope):
        calls.append(envelope["id"])
        return {"ok": True}

    with ThreadPoolExecutor(max_workers=2) as pool:
        stats = list(
            pool.map(
                lambda _: db_outbox.drain(dispatch, publish_to_neuro_bus=False),
                range(2),
            )
        )
    assert calls == [records[0].event_id]
    assert sum(s["sent"] for s in stats) == 1


@pytest.mark.parametrize(
    "event_name, payload, expected",
    [
        ("ops.intake.customer_ticket", {}, "pending"),
        ("payment.paid", {}, "uncertain"),
        ("ops.intake.customer_ticket", {"intake_source": "private_mod_rework"}, "uncertain"),
    ],
)
def test_expired_deliveries_retain_identity_and_fence_late_workers(
    factory, event_name, payload, expected
):
    with factory() as db:
        row = db_outbox.enqueue(db, event_name, "stable", payload)
        db.commit()
        row_id, event_id = row.id, row.event_id
    token = db_outbox.claim_record(row_id)
    with factory() as db:
        db.query(models.OutboxEvent).filter_by(id=row_id).update(
            {"claim_until": datetime(2000, 1, 1)}
        )
        db.commit()
    assert db_outbox.recover_expired_claims() == 1
    db_outbox.mark_dispatched(row_id, claim_token=token)
    db_outbox.mark_failed(row_id, "late failure", terminal=True, claim_token=token)
    with factory() as db:
        row = db.get(models.OutboxEvent, row_id)
        assert row.status == expected and row.event_id == event_id and row.attempts == 0
        assert db.query(models.OutboxDeadLetter).count() == 0


def test_unique_enqueue_collision_preserves_callers_business_transaction(factory, monkeypatch):
    with factory() as db:
        db_outbox.enqueue(db, "test.event", "existing", {})
        db.commit()
    with factory() as db:
        business = models.IncidentEvent(event_type="on_error", source="business")
        db.add(business)
        db.flush()
        original_query = db.query

        class MissOnce:
            def filter(self, *args):
                return self

            def first(self):
                return None

        calls = []

        def hide_first(*args):
            calls.append(1)
            return MissOnce() if len(calls) == 1 else original_query(*args)

        monkeypatch.setattr(db, "query", hide_first)
        assert db_outbox.enqueue(db, "test.event", "existing", {}) is None
        db.commit()
    with factory() as db:
        assert db.query(models.IncidentEvent).filter_by(source="business").count() == 1
        assert db.query(models.OutboxEvent).count() == 1
