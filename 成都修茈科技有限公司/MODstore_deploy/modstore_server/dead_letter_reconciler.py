# mypy: disable-error-code="assignment, operator"
"""Audited automatic resolution for outbox dead letters.

Infrastructure failures can become stale operational debt after the original
cause is gone.  Replaying every row is unsafe: a historical refund/payment
event may execute the business effect twice.  This reconciler therefore only
replays explicitly allow-listed idempotent event families and quarantines the
rest while retaining the complete row as audit evidence.
"""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from modstore_server.models import OutboxDeadLetter, OutboxEvent, get_session_factory

_DISK_FULL_MARKERS = ("no space left on device", "enospc")
_SENSITIVE_MARKERS = (
    "payment",
    "refund",
    "payout",
    "settlement",
    "withdraw",
    "invoice",
    "transaction",
    "order.paid",
    "decision_made",
)
_DEFAULT_SAFE_REPLAY_PREFIXES = "system.,observability.,telemetry.,cache.,knowledge."


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _event_age_hours(row: OutboxDeadLetter, now: datetime) -> float:
    happened = row.moved_at or row.created_at or now
    if happened.tzinfo is not None:
        happened = happened.astimezone(UTC).replace(tzinfo=None)
    return max(0.0, (now - happened).total_seconds() / 3600.0)


def _safe_replay_prefixes() -> tuple[str, ...]:
    raw = os.environ.get("MODSTORE_DLQ_SAFE_REPLAY_PREFIXES", _DEFAULT_SAFE_REPLAY_PREFIXES)
    return tuple(item.strip().lower() for item in str(raw).split(",") if item.strip())


def _is_sensitive(row: OutboxDeadLetter) -> bool:
    haystack = " ".join(
        (
            str(row.event_name or ""),
            str(row.payload_json or ""),
            str(row.aggregate_id or ""),
        )
    ).lower()
    return any(marker in haystack for marker in _SENSITIVE_MARKERS)


def _is_disk_full(row: OutboxDeadLetter) -> bool:
    error = str(row.last_error or "").lower()
    return any(marker in error for marker in _DISK_FULL_MARKERS)


def _events_dir() -> Path:
    from modstore_server.webhook_dispatcher import _events_dir as resolve_events_dir

    return resolve_events_dir()


def verify_storage_recovered() -> dict[str, Any]:
    """Prove the event sink is writable and has the configured free-space floor."""

    path = _events_dir()
    minimum = max(0, _env_int("MODSTORE_DLQ_MIN_FREE_BYTES", 1024**3))
    try:
        usage = os.statvfs(path)
        free_bytes = int(usage.f_bavail * usage.f_frsize)
        if free_bytes < minimum:
            return {
                "ok": False,
                "path": str(path),
                "free_bytes": free_bytes,
                "minimum_free_bytes": minimum,
                "reason": "free_space_below_floor",
            }
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".dlq-write-probe-",
            dir=path,
            delete=True,
        ) as probe:
            probe.write(b"xcagi-dlq-write-probe")
            probe.flush()
            os.fsync(probe.fileno())
        return {
            "ok": True,
            "path": str(path),
            "free_bytes": free_bytes,
            "minimum_free_bytes": minimum,
            "reason": "storage_writable",
        }
    except OSError as exc:
        return {
            "ok": False,
            "path": str(path),
            "free_bytes": 0,
            "minimum_free_bytes": minimum,
            "reason": f"storage_probe_failed:{type(exc).__name__}",
        }


def _schedule_replay(session: Any, row: OutboxDeadLetter, now: datetime) -> bool:
    source = None
    if row.source_outbox_id:
        source = session.query(OutboxEvent).filter(OutboxEvent.id == row.source_outbox_id).first()
    if source is None:
        source = session.query(OutboxEvent).filter(OutboxEvent.event_id == row.event_id).first()
    if source is None:
        return False
    source.status = "pending"
    source.attempts = 0
    source.last_error = ""
    source.dispatched_at = None
    row.resolution_status = "replay_scheduled"
    row.resolution_action = "automatic_replay"
    row.resolution_note = "transient storage failure recovered; idempotent event allow-list matched"
    row.resolved_at = now
    row.replay_outbox_id = int(source.id)
    return True


def _quarantine(row: OutboxDeadLetter, now: datetime, *, sensitive: bool) -> None:
    row.resolution_status = "quarantined"
    row.resolution_action = "no_replay"
    if sensitive:
        row.resolution_note = (
            "transient storage failure recovered; historical high-impact event retained "
            "without replay to prevent duplicate payment/refund/business effects"
        )
    else:
        row.resolution_note = (
            "transient storage failure recovered; event family is not on the idempotent "
            "automatic replay allow-list"
        )
    row.resolved_at = now


def reconcile_dead_letters(*, limit: int = 200, now: datetime | None = None) -> dict[str, Any]:
    """Resolve eligible infrastructure DLQ rows without erasing their evidence."""

    checked_at = now or _utcnow_naive()
    if checked_at.tzinfo is not None:
        checked_at = checked_at.astimezone(UTC).replace(tzinfo=None)
    min_age_hours = max(1, _env_int("MODSTORE_DLQ_AUTO_RESOLVE_MIN_AGE_HOURS", 24))
    storage = verify_storage_recovered()
    prefixes = _safe_replay_prefixes()
    stats = {
        "ok": True,
        "checked": 0,
        "replay_scheduled": 0,
        "quarantined": 0,
        "deferred": 0,
        "unresolved_count": 0,
        "storage": storage,
    }

    sf = get_session_factory()
    with sf() as session:
        rows = (
            session.query(OutboxDeadLetter)
            .filter(OutboxDeadLetter.resolved_at.is_(None))
            .order_by(OutboxDeadLetter.id.asc())
            .limit(max(1, min(int(limit), 1000)))
            .all()
        )
        for row in rows:
            stats["checked"] += 1
            row.last_reconciled_at = checked_at
            if not _is_disk_full(row) or _event_age_hours(row, checked_at) < min_age_hours:
                stats["deferred"] += 1
                continue
            if not storage.get("ok"):
                stats["deferred"] += 1
                continue

            event_name = str(row.event_name or "").lower()
            safe_replay = any(event_name.startswith(prefix) for prefix in prefixes)
            if safe_replay and _schedule_replay(session, row, checked_at):
                stats["replay_scheduled"] += 1
            else:
                _quarantine(row, checked_at, sensitive=_is_sensitive(row))
                stats["quarantined"] += 1

        session.commit()
        stats["unresolved_count"] = int(
            session.query(OutboxDeadLetter).filter(OutboxDeadLetter.resolved_at.is_(None)).count()
        )
    return stats


def dead_letter_health() -> dict[str, Any]:
    sf = get_session_factory()
    with sf() as session:
        unresolved = int(
            session.query(OutboxDeadLetter).filter(OutboxDeadLetter.resolved_at.is_(None)).count()
        )
        resolved = int(
            session.query(OutboxDeadLetter)
            .filter(OutboxDeadLetter.resolved_at.is_not(None))
            .count()
        )
    return {
        "ok": unresolved == 0,
        "unresolved_count": unresolved,
        "resolved_count": resolved,
    }


__all__ = ["dead_letter_health", "reconcile_dead_letters", "verify_storage_recovered"]
