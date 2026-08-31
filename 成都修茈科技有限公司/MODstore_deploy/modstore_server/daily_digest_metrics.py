"""Daily-digest metric semantics shared by the renderer and tests."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


# IncidentEvent is an append-only event ledger.  Only failure/escalation event
# types are pending incidents; lifecycle signals such as git.push,
# employee.task.done, backup.completed and schedule.tick remain useful event
# volume, but must never turn the digest orange by themselves.
ACTIONABLE_INCIDENT_EVENT_TYPES = frozenset(
    {
        "on_error",
        "on_quality_fail",
        "on_coverage_miss",
        "employee.task.failed",
        "ops.change_request.escalated",
        "ci.failed",
        "payment.anomaly",
        "customer.complaint",
        "security.alert",
        "log.anomaly",
        "incident.unknown",
        "backup.failed",
        "backup.ondemand_failed",
        "backup.dr_guard.escalated",
    }
)


def summarize_digest_events(rows: Iterable[Any]) -> tuple[int, int]:
    """Return ``(event_volume, unique_actionable_incidents)`` for ledger rows."""

    total = 0
    actionable: set[tuple[str, str]] = set()
    for row in rows:
        total += 1
        event_type = str(getattr(row, "event_type", "") or "").strip()
        if event_type not in ACTIONABLE_INCIDENT_EVENT_TYPES:
            continue
        fingerprint = str(getattr(row, "fingerprint", "") or "").strip()
        if not fingerprint:
            fingerprint = f"row:{getattr(row, 'id', total)}"
        actionable.add((event_type, fingerprint))
    return total, len(actionable)


def is_burn_in_task(task: str) -> bool:
    """Burn-in acceptance runs are quality probes, not production executions."""

    return str(task or "").startswith("[duty-burn-in:")


__all__ = [
    "ACTIONABLE_INCIDENT_EVENT_TYPES",
    "is_burn_in_task",
    "summarize_digest_events",
]
