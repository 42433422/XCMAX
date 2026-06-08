"""Transactional event outbox backed by the application database.

The legacy file outbox in :mod:`modstore_server.eventing.outbox` is kept as an
append-only audit log; this module adds the missing transactional guarantee:
business writes and the outbox row are committed in the same SQLAlchemy
session, and a background dispatcher then drains pending rows to the
business webhook (and any in-process subscriber).

Design notes
------------
* Same DB as the rest of the application (``models.OutboxEvent``) so the
  business transaction and the outbox insert succeed or fail together. No
  silent two-phase write to the file system.
* ``event_id`` is unique to make consumer-side replay idempotent. The
  dispatcher uses ``stable_event_id`` from
  :mod:`modstore_server.webhook_dispatcher` so retries always land on the
  same id.
* Status state machine: ``pending`` → ``dispatched`` (success) /
  ``failed`` (terminal after exhausting retries). Failed rows are not
  silently dropped — the admin webhook replay still works because the
  envelope is reconstructed from the row.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterator

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from modstore_server.eventing.contracts import (
    canonical_event_name,
    event_version,
    validate_payload,
)
from modstore_server.eventing.events import DomainEvent, new_event
from modstore_server.eventing.global_bus import neuro_bus
from modstore_server.models import OutboxDeadLetter, OutboxEvent, get_session_factory

logger = logging.getLogger(__name__)

DispatcherFn = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class OutboxRecord:
    id: int
    event_id: str
    event_name: str
    event_version: int
    aggregate_id: str
    idempotency_key: str
    producer: str
    payload: dict[str, Any]
    status: str
    attempts: int
    last_error: str

    def to_envelope(self) -> dict[str, Any]:
        """Build the outbound webhook envelope (matching ``build_event``)."""
        return {
            "id": self.event_id,
            "type": self.event_name,
            "version": self.event_version,
            "source": self.producer,
            "aggregate_id": self.aggregate_id,
            "created_at": int(time.time()),
            "data": self.payload,
        }

    def to_domain_event(self) -> DomainEvent:
        return new_event(
            self.event_name,
            producer=self.producer,
            subject_id=self.aggregate_id,
            payload=self.payload,
            event_version=self.event_version,
            idempotency_key=self.idempotency_key or None,
        )


def _stable_event_id(event_name: str, aggregate_id: str) -> str:
    aggregate = (aggregate_id or "").strip()
    if aggregate:
        return f"{event_name}:{aggregate}"
    import hashlib

    digest = hashlib.sha256(f"{event_name}:{time.time_ns()}".encode("utf-8")).hexdigest()[:16]
    return f"{event_name}:{digest}"


def enqueue(
    session: Session,
    event_name: str,
    aggregate_id: str,
    payload: dict[str, Any],
    *,
    producer: str = "modstore-python",
    event_id: str | None = None,
    idempotency_key: str | None = None,
) -> OutboxEvent | None:
    """Insert an event into the outbox as part of an existing transaction.

    The caller is responsible for ``session.commit()`` so the business write
    and the outbox row land atomically. Returns ``None`` if an event with the
    same ``event_id`` already exists (idempotent enqueue).
    """
    canonical = canonical_event_name(event_name)
    missing = validate_payload(canonical, payload)
    if missing:
        logger.warning(
            "outbox payload missing recommended fields event=%s fields=%s",
            canonical,
            ",".join(missing),
        )
    eid = event_id or _stable_event_id(canonical, aggregate_id)
    row = OutboxEvent(
        event_id=eid,
        event_name=canonical,
        event_version=event_version(canonical),
        aggregate_id=aggregate_id or "",
        idempotency_key=idempotency_key or f"{canonical}:{aggregate_id or eid}",
        producer=producer,
        payload_json=json.dumps(payload, ensure_ascii=False, default=str),
        status="pending",
        attempts=0,
        last_error="",
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = session.query(OutboxEvent).filter(OutboxEvent.event_id == eid).first()
        if existing is None:
            raise
        logger.debug("outbox enqueue idempotent skip event_id=%s", eid)
        return None
    return row


def _row_to_record(row: OutboxEvent) -> OutboxRecord:
    try:
        payload = json.loads(row.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    return OutboxRecord(
        id=int(row.id),
        event_id=str(row.event_id),
        event_name=str(row.event_name),
        event_version=int(row.event_version or 1),
        aggregate_id=str(row.aggregate_id or ""),
        idempotency_key=str(row.idempotency_key or ""),
        producer=str(row.producer or "modstore-python"),
        payload=payload if isinstance(payload, dict) else {},
        status=str(row.status or "pending"),
        attempts=int(row.attempts or 0),
        last_error=str(row.last_error or ""),
    )


@contextmanager
def _session_scope() -> Iterator[Session]:
    sf = get_session_factory()
    session = sf()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def fetch_pending(limit: int = 50) -> list[OutboxRecord]:
    sf = get_session_factory()
    with sf() as session:
        rows = (
            session.query(OutboxEvent)
            .filter(OutboxEvent.status == "pending")
            .order_by(OutboxEvent.id.asc())
            .limit(max(1, int(limit)))
            .all()
        )
        return [_row_to_record(r) for r in rows]


def mark_dispatched(record_id: int) -> None:
    with _session_scope() as session:
        row = session.query(OutboxEvent).filter(OutboxEvent.id == record_id).first()
        if row is None:
            return
        row.status = "dispatched"
        row.last_error = ""
        row.dispatched_at = datetime.now(timezone.utc)


def mark_failed(record_id: int, error: str, *, terminal: bool) -> None:
    with _session_scope() as session:
        row = session.query(OutboxEvent).filter(OutboxEvent.id == record_id).first()
        if row is None:
            return
        row.attempts = int(row.attempts or 0) + 1
        row.last_error = (error or "")[:1000]
        if terminal:
            row.status = "failed"
            session.add(
                OutboxDeadLetter(
                    source_outbox_id=int(row.id),
                    event_id=str(row.event_id),
                    event_name=str(row.event_name),
                    event_version=int(row.event_version or 1),
                    aggregate_id=str(row.aggregate_id or ""),
                    idempotency_key=str(row.idempotency_key or ""),
                    producer=str(row.producer or "modstore-python"),
                    payload_json=str(row.payload_json or "{}"),
                    attempts=int(row.attempts or 0),
                    last_error=str(row.last_error or "")[:2000],
                )
            )


def _max_attempts() -> int:
    try:
        return max(1, min(20, int(os.environ.get("MODSTORE_OUTBOX_MAX_ATTEMPTS", "5"))))
    except ValueError:
        return 5


def drain(
    dispatcher: DispatcherFn | None = None,
    *,
    limit: int = 50,
    publish_to_neuro_bus: bool = True,
) -> dict[str, int]:
    """Drain pending outbox rows once.

    ``dispatcher`` defaults to :func:`webhook_dispatcher.dispatch_event`. The
    function never raises — failures are persisted on the row and caller can
    decide to retry on the next tick.
    """
    if dispatcher is None:
        from modstore_server import webhook_dispatcher

        dispatcher = webhook_dispatcher.dispatch_event

    sent = 0
    failed = 0
    skipped = 0
    max_attempts = _max_attempts()
    for record in fetch_pending(limit=limit):
        if publish_to_neuro_bus:
            try:
                neuro_bus.publish(record.to_domain_event())
            except Exception:
                logger.exception("neuro_bus publish failed event_id=%s", record.event_id)
        try:
            result = dispatcher(record.to_envelope())
        except Exception as exc:
            logger.exception("outbox dispatcher raised event_id=%s", record.event_id)
            mark_failed(
                record.id,
                str(exc),
                terminal=record.attempts + 1 >= max_attempts,
            )
            failed += 1
            continue
        if result.get("ok"):
            mark_dispatched(record.id)
            sent += 1
        elif result.get("skipped"):
            skipped += 1
            mark_failed(
                record.id,
                str(result.get("message") or "skipped"),
                terminal=False,
            )
        else:
            failed += 1
            mark_failed(
                record.id,
                str(result.get("message") or result.get("body") or "delivery failed"),
                terminal=record.attempts + 1 >= max_attempts,
            )
    return {"sent": sent, "failed": failed, "skipped": skipped}


class OutboxDispatcherWorker:
    """Tiny background worker draining the outbox on a fixed cadence.

    Uses a daemon thread so unit tests and one-shot scripts do not have to
    manage shutdown. Production deployments should still call
    :meth:`stop` during graceful shutdown.
    """

    def __init__(self, *, interval_seconds: float = 5.0, batch_size: int = 50):
        self.interval_seconds = max(0.1, float(interval_seconds))
        self.batch_size = max(1, int(batch_size))
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="modstore-outbox-dispatcher", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float | None = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                drain(limit=self.batch_size)
            except Exception:
                logger.exception("outbox worker drain loop failed")
            self._stop.wait(self.interval_seconds)


_default_worker: OutboxDispatcherWorker | None = None


def start_default_worker() -> OutboxDispatcherWorker:
    """Start (or return) a process-singleton outbox worker.

    Disabled when ``MODSTORE_OUTBOX_WORKER_DISABLED=1`` so unit tests can opt
    out and stay deterministic.
    """
    global _default_worker
    if (os.environ.get("MODSTORE_OUTBOX_WORKER_DISABLED") or "").strip() == "1":
        return _default_worker or OutboxDispatcherWorker()
    if _default_worker is None:
        try:
            interval = float(os.environ.get("MODSTORE_OUTBOX_INTERVAL_SECONDS", "5"))
        except ValueError:
            interval = 5.0
        _default_worker = OutboxDispatcherWorker(interval_seconds=interval)
        _default_worker.start()
    return _default_worker


__all__ = [
    "OutboxDispatcherWorker",
    "OutboxRecord",
    "drain",
    "enqueue",
    "fetch_pending",
    "mark_dispatched",
    "mark_failed",
    "start_default_worker",
]
