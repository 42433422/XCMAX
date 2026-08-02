"""Scheduler registrations for low-frequency maintenance jobs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from apscheduler.triggers.interval import IntervalTrigger


def register_dead_letter_reconciliation(
    scheduler: Any,
    run_tracked: Callable[[str, Callable[[], Any]], dict[str, Any]],
    env_int: Callable[[str, int], int],
    cleanup_grace: Callable[[], int],
    logger: Any,
) -> None:
    def reconcile() -> None:
        try:
            from modstore_server.dead_letter_reconciler import reconcile_dead_letters

            result = run_tracked(
                "dead_letter_reconciler", lambda: reconcile_dead_letters(limit=200)
            )
            if result.get("checked") or result.get("unresolved_count"):
                logger.info(
                    "dead-letter reconciliation checked=%s replay=%s quarantined=%s deferred=%s unresolved=%s storage_ok=%s",
                    result.get("checked"),
                    result.get("replay_scheduled"),
                    result.get("quarantined"),
                    result.get("deferred"),
                    result.get("unresolved_count"),
                    bool((result.get("storage") or {}).get("ok")),
                )
        except Exception:
            logger.exception("dead-letter reconciliation failed")

    scheduler.add_job(
        reconcile,
        IntervalTrigger(minutes=max(1, env_int("MODSTORE_DLQ_RECONCILE_MINUTES", 5))),
        id="dead_letter_reconciler",
        replace_existing=True,
        misfire_grace_time=cleanup_grace(),
        coalesce=True,
        max_instances=1,
    )
    reconcile()
