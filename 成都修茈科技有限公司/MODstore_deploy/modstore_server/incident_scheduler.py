"""Register the durable incident-dispatch scheduler job."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from apscheduler.triggers.interval import IntervalTrigger

from modstore_server.incident_bus import dispatch_pending_incidents


def register_pending_incident_dispatch(
    scheduler: Any, env_int: Callable[[str, int], int], cleanup_grace: Callable[[], int]
) -> None:
    scheduler.add_job(
        dispatch_pending_incidents,
        IntervalTrigger(seconds=max(15, env_int("MODSTORE_INCIDENT_DISPATCH_PENDING_INTERVAL", 30))),
        id="incident_dispatch_pending",
        replace_existing=True,
        misfire_grace_time=cleanup_grace(),
        coalesce=True,
        max_instances=1,
        kwargs={"max_age_seconds": 3600, "limit": 5},
    )
