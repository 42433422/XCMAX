"""Tests for the transactional event outbox.

The outbox is the missing piece that turns the existing in-process
``NeuroBus`` plus business webhook into a durable, retryable delivery
pipeline. These tests pin the contract so future refactors do not silently
drop a critical guarantee (idempotent enqueue, atomic-with-business-write,
retry-with-terminal-failed-state).
"""

from __future__ import annotations

import importlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import modstore_server.models as models
from modstore_server.eventing import db_outbox


@pytest.fixture
def fresh_db(monkeypatch):
    """Create a clean in-memory SQLite engine and rebind the global session.

    We can't simply reuse :func:`models.init_db` because it pulls in plan
    template seed data unrelated to the outbox; instead we recreate just the
    ORM metadata against the temp engine.
    """

    engine = create_engine("sqlite:///:memory:", future=True)
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    monkeypatch.setattr(models, "_engine", engine)
    monkeypatch.setattr(models, "_SessionFactory", factory)
    yield factory
    engine.dispose()


def test_enqueue_persists_pending_row(fresh_db):
    factory = fresh_db
    with factory() as session:
        row = db_outbox.enqueue(
            session,
            "payment.paid",
            "ORDER1",
            {
                "out_trade_no": "ORDER1",
                "user_id": 1,
                "subject": "vip",
                "total_amount": "9.90",
                "order_kind": "plan",
            },
        )
        session.commit()
    assert row is not None
    pending = db_outbox.fetch_pending()
    assert len(pending) == 1
    record = pending[0]
    assert record.event_name == "payment.paid"
    assert record.event_id == "payment.paid:ORDER1"
    assert record.aggregate_id == "ORDER1"
    assert record.status == "pending"
    envelope = record.to_envelope()
    assert envelope["type"] == "payment.paid"
    assert envelope["aggregate_id"] == "ORDER1"
    assert envelope["data"]["out_trade_no"] == "ORDER1"


def test_enqueue_canonicalises_legacy_event_alias(fresh_db):
    factory = fresh_db
    with factory() as session:
        row = db_outbox.enqueue(session, "payment.order_paid", "ORDER2", {"out_trade_no": "ORDER2"})
        session.commit()
    assert row is not None
    pending = db_outbox.fetch_pending()
    assert pending[0].event_name == "payment.paid"
    assert pending[0].event_id == "payment.paid:ORDER2"


def test_enqueue_rolls_back_with_business_failure(fresh_db):
    """Outbox row must not survive a failed business transaction."""

    factory = fresh_db
    with factory() as session:
        db_outbox.enqueue(session, "payment.paid", "ORDER3", {"out_trade_no": "ORDER3"})
        session.rollback()
    assert db_outbox.fetch_pending() == []


def test_enqueue_is_idempotent_per_event_id(fresh_db):
    factory = fresh_db
    with factory() as session:
        db_outbox.enqueue(session, "payment.paid", "ORDER4", {"out_trade_no": "ORDER4"})
        session.commit()
    with factory() as session:
        again = db_outbox.enqueue(session, "payment.paid", "ORDER4", {"out_trade_no": "ORDER4"})
        session.commit()
    assert again is None
    assert len(db_outbox.fetch_pending()) == 1


def test_drain_marks_row_dispatched_on_success(fresh_db):
    factory = fresh_db
    with factory() as session:
        db_outbox.enqueue(session, "payment.paid", "ORDER5", {"out_trade_no": "ORDER5"})
        session.commit()

    captured = {}

    def fake_dispatcher(envelope):
        captured["envelope"] = envelope
        return {"ok": True, "status_code": 200}

    stats = db_outbox.drain(fake_dispatcher)
    assert stats == {"sent": 1, "failed": 0, "skipped": 0}
    assert captured["envelope"]["type"] == "payment.paid"
    assert db_outbox.fetch_pending() == []


def test_drain_records_skipped_without_terminal_failure(fresh_db):
    factory = fresh_db
    with factory() as session:
        db_outbox.enqueue(session, "payment.paid", "ORDER6", {"out_trade_no": "ORDER6"})
        session.commit()

    def skip_dispatcher(_envelope):
        return {"ok": False, "skipped": True, "message": "no webhook url"}

    stats = db_outbox.drain(skip_dispatcher)
    assert stats["sent"] == 0
    assert stats["skipped"] == 1
    pending = db_outbox.fetch_pending()
    assert len(pending) == 1
    assert pending[0].attempts == 1
    assert pending[0].status == "pending"


def test_drain_retries_then_marks_failed_terminal(fresh_db, monkeypatch):
    factory = fresh_db
    with factory() as session:
        db_outbox.enqueue(session, "payment.paid", "ORDER7", {"out_trade_no": "ORDER7"})
        session.commit()

    monkeypatch.setenv("MODSTORE_OUTBOX_MAX_ATTEMPTS", "2")
    importlib.reload(db_outbox)

    def boom(_envelope):
        return {"ok": False, "message": "HTTP 500"}

    stats = db_outbox.drain(boom)
    assert stats == {"sent": 0, "failed": 1, "skipped": 0}
    pending_after_first = db_outbox.fetch_pending()
    assert len(pending_after_first) == 1
    assert pending_after_first[0].attempts == 1
    assert pending_after_first[0].status == "pending"
    assert pending_after_first[0].last_error == "HTTP 500"

    db_outbox.drain(boom)
    assert db_outbox.fetch_pending() == []


def test_drain_publishes_to_neuro_bus(fresh_db, monkeypatch):
    factory = fresh_db
    with factory() as session:
        db_outbox.enqueue(session, "payment.paid", "ORDER8", {"out_trade_no": "ORDER8"})
        session.commit()

    seen = []

    class _Bus:
        def publish(self, event):
            seen.append(event)

    monkeypatch.setattr(db_outbox, "neuro_bus", _Bus())
    db_outbox.drain(lambda _e: {"ok": True})
    assert seen, "drain must republish the event onto the in-process NeuroBus"
    assert seen[0].event_name == "payment.paid"


def test_drain_handles_dispatcher_exception(fresh_db):
    factory = fresh_db
    with factory() as session:
        db_outbox.enqueue(session, "payment.paid", "ORDER9", {"out_trade_no": "ORDER9"})
        session.commit()

    def explodes(_envelope):
        raise RuntimeError("connection refused")

    stats = db_outbox.drain(explodes)
    assert stats["failed"] == 1
    pending = db_outbox.fetch_pending()
    assert len(pending) == 1
    assert pending[0].attempts == 1
    assert "connection refused" in pending[0].last_error


def test_worker_start_stop_idempotent():
    """The default worker must start once and stop cleanly under tests."""

    worker = db_outbox.OutboxDispatcherWorker(interval_seconds=10.0)
    worker.start()
    worker.start()
    worker.stop()
    worker.stop()


def test_webhook_dispatcher_enqueue_event_uses_outbox(fresh_db):
    """``webhook_dispatcher.enqueue_event`` is the supported transactional API."""

    from modstore_server import webhook_dispatcher

    factory = fresh_db
    with factory() as session:
        row = webhook_dispatcher.enqueue_event(
            session,
            "payment.paid",
            "ORDERTX",
            {"out_trade_no": "ORDERTX"},
            source="payment-test",
        )
        session.commit()
    assert row is not None
    pending = db_outbox.fetch_pending()
    assert len(pending) == 1
    assert pending[0].producer == "payment-test"
