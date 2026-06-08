"""Scheduler cron: periodic post-deploy HTTP smoke (health + market/download)."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from apscheduler.schedulers.base import BaseScheduler

logger = logging.getLogger(__name__)


def cron_smoke_enabled() -> bool:
    return os.environ.get("MODSTORE_POST_DEPLOY_SMOKE_CRON_ENABLED", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def interval_trigger_for_post_deploy_smoke():
    from apscheduler.triggers.interval import IntervalTrigger

    try:
        smoke_min = int(os.environ.get("MODSTORE_POST_DEPLOY_SMOKE_INTERVAL_MIN", "30"))
    except ValueError:
        smoke_min = 30
    return IntervalTrigger(minutes=max(5, smoke_min))


def run_post_deploy_smoke_job() -> Dict[str, Any]:
    """Run smoke probes; log failures for SLO / on-call."""
    from modstore_server.post_deploy_smoke import run_post_deploy_smoke

    out = run_post_deploy_smoke()
    if not out.get("ok") and not out.get("skipped"):
        logger.warning("post_deploy_smoke failed: %s", out.get("probes"))
    return out


def register_post_deploy_smoke_scheduler(scheduler: Any) -> None:
    """Register interval job when ``MODSTORE_POST_DEPLOY_SMOKE_CRON_ENABLED=1``."""
    if not cron_smoke_enabled():
        return
    scheduler.add_job(
        run_post_deploy_smoke_job,
        interval_trigger_for_post_deploy_smoke(),
        id="post_deploy_smoke_interval",
        replace_existing=True,
    )


def cron_smoke_interval_minutes() -> Optional[int]:
    """Expose configured interval for tests / env verify."""
    if not cron_smoke_enabled():
        return None
    try:
        return max(5, int(os.environ.get("MODSTORE_POST_DEPLOY_SMOKE_INTERVAL_MIN", "30")))
    except ValueError:
        return 30
