from __future__ import annotations

from datetime import datetime, timedelta

import modstore_server.models as models
from modstore_server import dead_letter_reconciler


def _init_db(tmp_path, monkeypatch):
    models._engine = None
    models._SessionFactory = None
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "dlq.sqlite"))
    events_dir = tmp_path / "webhook-events"
    monkeypatch.setenv("MODSTORE_WEBHOOK_EVENTS_DIR", str(events_dir))
    monkeypatch.setenv("MODSTORE_DLQ_MIN_FREE_BYTES", "0")
    monkeypatch.setenv("MODSTORE_DLQ_AUTO_RESOLVE_MIN_AGE_HOURS", "1")
    monkeypatch.setenv("MODSTORE_DLQ_SAFE_REPLAY_PREFIXES", "system.,telemetry.")
    models.init_db()
    return models.get_session_factory()


def _add_dead_letter(session, *, event_id: str, event_name: str, payload: str):
    source = models.OutboxEvent(
        event_id=event_id,
        event_name=event_name,
        event_version=1,
        aggregate_id=event_id,
        idempotency_key=event_id,
        producer="test",
        payload_json=payload,
        status="failed",
        attempts=5,
        last_error="No space left on device",
    )
    session.add(source)
    session.commit()
    session.refresh(source)
    row = models.OutboxDeadLetter(
        source_outbox_id=source.id,
        event_id=event_id,
        event_name=event_name,
        event_version=1,
        aggregate_id=event_id,
        idempotency_key=event_id,
        producer="test",
        payload_json=payload,
        attempts=5,
        last_error="[Errno 28] No space left on device",
        created_at=datetime.now() - timedelta(days=2),
        moved_at=datetime.now() - timedelta(days=2),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return int(source.id), int(row.id)


def test_reconcile_replays_allowlisted_event_and_quarantines_refund(tmp_path, monkeypatch):
    sf = _init_db(tmp_path, monkeypatch)
    with sf() as session:
        safe_source_id, safe_dlq_id = _add_dead_letter(
            session,
            event_id="system.cache_refresh:1",
            event_name="system.cache_refresh",
            payload='{"scope":"catalog"}',
        )
        refund_source_id, refund_dlq_id = _add_dead_letter(
            session,
            event_id="customer_service.decision_made:refund-1",
            event_name="customer_service.decision_made",
            payload='{"intent":"refund","decision":"approved"}',
        )

    result = dead_letter_reconciler.reconcile_dead_letters(limit=20)

    assert result["ok"] is True
    assert result["storage"]["ok"] is True
    assert result["replay_scheduled"] == 1
    assert result["quarantined"] == 1
    assert result["unresolved_count"] == 0
    with sf() as session:
        safe_source = session.get(models.OutboxEvent, safe_source_id)
        refund_source = session.get(models.OutboxEvent, refund_source_id)
        safe_dlq = session.get(models.OutboxDeadLetter, safe_dlq_id)
        refund_dlq = session.get(models.OutboxDeadLetter, refund_dlq_id)
        assert safe_source.status == "pending"
        assert safe_source.attempts == 0
        assert safe_dlq.resolution_status == "replay_scheduled"
        assert safe_dlq.replay_outbox_id == safe_source_id
        assert refund_source.status == "failed"
        assert refund_dlq.resolution_status == "quarantined"
        assert refund_dlq.resolution_action == "no_replay"
        assert "duplicate" in refund_dlq.resolution_note
        assert refund_dlq.resolved_at is not None

    models._engine = None
    models._SessionFactory = None


def test_reconcile_defers_when_storage_has_not_recovered(tmp_path, monkeypatch):
    sf = _init_db(tmp_path, monkeypatch)
    with sf() as session:
        _, dlq_id = _add_dead_letter(
            session,
            event_id="system.cache_refresh:2",
            event_name="system.cache_refresh",
            payload="{}",
        )
    monkeypatch.setattr(
        dead_letter_reconciler,
        "verify_storage_recovered",
        lambda: {"ok": False, "reason": "free_space_below_floor"},
    )

    result = dead_letter_reconciler.reconcile_dead_letters(limit=20)

    assert result["replay_scheduled"] == 0
    assert result["quarantined"] == 0
    assert result["deferred"] == 1
    assert result["unresolved_count"] == 1
    with sf() as session:
        row = session.get(models.OutboxDeadLetter, dlq_id)
        assert row.resolved_at is None
        assert row.last_reconciled_at is not None

    models._engine = None
    models._SessionFactory = None
