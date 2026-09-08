"""Canonical UTC deadlines for durable, once-only task scheduling."""

from datetime import UTC, datetime
from typing import Any


def normalize_scheduled_at(value: Any) -> str:
    """Require an explicit timezone; never silently use the server's timezone."""
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        raise ValueError("scheduled_at 必须是带时区的 ISO 8601 时间")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("scheduled_at 必须包含时区")
    return parsed.astimezone(UTC).isoformat()


def execution_available_at(run: Any, now: str) -> str:
    schedule = run.metadata.get("schedule")
    if not isinstance(schedule, dict):
        return now
    due = normalize_scheduled_at(schedule.get("scheduled_at"))
    # Overdue approved tasks run once on recovery. Pausing and resuming before
    # the deadline must not advance them to the current time.
    return max(now, due) if due else now
