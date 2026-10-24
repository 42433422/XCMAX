# mypy: disable-error-code="arg-type, assignment"
"""Transactional outbox with stable event identities and fenced SQL delivery claims.

Business writes and enqueue share one transaction. Each delivery claims the row
before sending. Expired incident intake resumes its unique inbox; uncertain
external sends remain held for reconciliation instead of being blindly replayed.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Iterator

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from modstore_server.eventing.contracts import canonical_event_name, event_version, validate_payload
from modstore_server.eventing.events import DomainEvent, new_event
from modstore_server.eventing.global_bus import neuro_bus
from modstore_server.models import OutboxDeadLetter, OutboxEvent, get_session_factory
from modstore_server.operational_errors import RECOVERABLE_ERRORS

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

    digest = hashlib.sha256(f"{event_name}:{time.time_ns()}".encode()).hexdigest()[:16]
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
    # 先做幂等短路，避免在主事务中产生重复入账。
    existing = session.query(OutboxEvent).filter(OutboxEvent.event_id == eid).first()
    if existing is not None:
        logger.debug("outbox enqueue idempotent skip event_id=%s", eid)
        return None

    connection = session.connection()
    driver = connection.connection.driver_connection
    if driver is None:
        raise RuntimeError("database connection unavailable")
    if connection.dialect.name == "sqlite" and not driver.in_transaction:
        connection.exec_driver_sql(
            "BEGIN"
        )  # RELEASE SAVEPOINT must not commit the business transaction.
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
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
    except RECOVERABLE_ERRORS:
        session.rollback()
        raise
    finally:
        session.close()


def fetch_pending(
    limit: int = 50, *, aggregate_prefix: str = "", include_dispatched: bool = False
) -> list[OutboxRecord]:
    with get_session_factory()() as session:
        query = session.query(OutboxEvent).filter(
            OutboxEvent.status.in_(["pending", "dispatched"] if include_dispatched else ["pending"])
        )
        if aggregate_prefix:
            query = query.filter(
                OutboxEvent.aggregate_id.startswith(aggregate_prefix, autoescape=True)
            )
        rows = query.order_by(OutboxEvent.id.asc()).limit(max(1, int(limit))).all()
        return [_row_to_record(r) for r in rows]


def _database_time(session) -> datetime:
    value = session.execute(select(func.current_timestamp())).scalar_one()
    if not isinstance(value, datetime):
        raise RuntimeError("database clock unavailable")
    return value.replace(tzinfo=None)


def claim_record(record_id: int, *, lease_seconds: int = 300) -> str:
    token = uuid.uuid4().hex
    with _session_scope() as session:
        won = (
            session.query(OutboxEvent)
            .filter(
                OutboxEvent.id == record_id,
                OutboxEvent.status == "pending",
            )
            .update(
                {
                    "status": "dispatching",
                    "claim_token": token,
                    "claim_until": _database_time(session)
                    + timedelta(seconds=max(30, lease_seconds)),
                },
                synchronize_session=False,
            )
        )
    return token if won else ""


def recover_expired_claims() -> int:
    """Only the incident inbox makes replay safe; other unknown sends stay held."""
    with _session_scope() as session:
        now = _database_time(session)
        rows = (
            session.query(OutboxEvent)
            .filter(OutboxEvent.status == "dispatching", OutboxEvent.claim_until <= now)
            .all()
        )
        recovered = 0
        for row in rows:
            try:
                payload = json.loads(row.payload_json or "{}")
            except json.JSONDecodeError:
                payload = None
            replayable = (
                row.event_name == "ops.intake.customer_ticket"
                and isinstance(payload, dict)
                and payload.get("intake_source") != "private_mod_rework"
            )
            recovered += (
                session.query(OutboxEvent)
                .filter(
                    OutboxEvent.id == row.id,
                    OutboxEvent.status == "dispatching",
                    OutboxEvent.claim_token == row.claim_token,
                    OutboxEvent.claim_until <= now,
                )
                .update(
                    {
                        "status": "pending" if replayable else "uncertain",
                        "claim_token": "",
                        "claim_until": None,
                        "last_error": (
                            "previous delivery lease expired; resume original inbox identity"
                            if replayable
                            else "delivery outcome unknown; reconcile original event before replay"
                        ),
                    },
                    synchronize_session=False,
                )
            )
        return recovered


def mark_dispatched(record_id: int, *, claim_token: str = "") -> bool:
    with _session_scope() as session:
        query = session.query(OutboxEvent).filter(OutboxEvent.id == record_id)
        if claim_token:
            query = query.filter(
                OutboxEvent.claim_token == claim_token,
                OutboxEvent.status == "dispatching",
                OutboxEvent.claim_until > _database_time(session),
            )
        won = query.update(
            {
                "status": "dispatched",
                "last_error": "",
                "claim_token": "",
                "claim_until": None,
                "dispatched_at": datetime.now(UTC),
            },
            synchronize_session=False,
        )

    return bool(won)


def mark_failed(record_id: int, error: str, *, terminal: bool, claim_token: str = "") -> None:
    with _session_scope() as session:
        query = session.query(OutboxEvent).filter(OutboxEvent.id == record_id)
        if claim_token:
            query = query.filter(
                OutboxEvent.claim_token == claim_token,
                OutboxEvent.status == "dispatching",
                OutboxEvent.claim_until > _database_time(session),
            )
        won = query.update(
            {
                "attempts": OutboxEvent.attempts + 1,
                "last_error": (error or "")[:1000],
                "status": "failed" if terminal else "pending",
                "claim_token": "",
                "claim_until": None,
            },
            synchronize_session=False,
        )
        if not won:
            return
        row = session.get(OutboxEvent, record_id, populate_existing=True)
        if row is None:
            raise RuntimeError("claimed outbox row disappeared")
        if terminal:
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
    recover_expired_claims()
    for record in fetch_pending(limit=limit):
        token = claim_record(record.id)
        if not token:
            skipped += 1
            continue
        if publish_to_neuro_bus:
            try:
                neuro_bus.publish(record.to_domain_event())
            except RECOVERABLE_ERRORS:
                logger.exception("neuro_bus publish failed event_id=%s", record.event_id)
        try:
            if record.event_name == "ops.intake.customer_ticket":
                from modstore_server.customer_issue_intake import dispatch_issue_event

                result = dispatch_issue_event(record.to_envelope())
            else:
                result = dispatcher(record.to_envelope())
        except RECOVERABLE_ERRORS as exc:
            logger.exception("outbox dispatcher raised event_id=%s", record.event_id)
            mark_failed(
                record.id,
                str(exc),
                terminal=record.attempts + 1 >= max_attempts,
                claim_token=token,
            )
            failed += 1
            continue
        if result.get("ok"):
            if mark_dispatched(record.id, claim_token=token):
                sent += 1
            else:
                skipped += 1
        elif result.get("skipped"):
            skipped += 1
            mark_failed(
                record.id,
                str(result.get("message") or "skipped"),
                terminal=False,
                claim_token=token,
            )
        else:
            failed += 1
            mark_failed(
                record.id,
                str(result.get("message") or result.get("body") or "delivery failed"),
                terminal=record.attempts + 1 >= max_attempts,
                claim_token=token,
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
                from modstore_server.customer_issue_intake import recover_pending_incidents

                recover_pending_incidents(limit=self.batch_size)
            except RECOVERABLE_ERRORS:
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
