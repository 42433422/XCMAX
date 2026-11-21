"""Scheduler cron: periodic post-deploy HTTP smoke (health + market/download)."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, Dict, Optional

from modstore_server.operational_errors import RECOVERABLE_ERRORS

if TYPE_CHECKING:
    pass

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
    """Run smoke probes; publish an incident when probes fail."""
    from modstore_server.post_deploy_smoke import run_post_deploy_smoke

    out = run_post_deploy_smoke()
    if out.get("ok") or out.get("skipped"):
        return out

    # 部署后探活失败是发布链的第一道信号，只写 warning 等于没人知道。
    # 复用统一 incident 入口，让自维护循环能消费到这条失败。
    logger.warning("post_deploy_smoke failed: %s", out.get("probes"))
    try:
        from modstore_server.incident_bus import publish_unified_incident

        publish_unified_incident(
            scope="post_deploy_smoke",
            summary="部署后探活失败: " + ", ".join(_failed_probe_names(out)),
            source="post_deploy_smoke",
            event_type="on_error",
            fingerprint="post_deploy_smoke:failed",
            priority=80,
            payload={"probes": out.get("probes"), "result": out},
        )
    except RECOVERABLE_ERRORS as exc:
        logger.warning("post_deploy_smoke incident publish failed: %s", exc)
    return out


def _failed_probe_names(out: Dict[str, Any]) -> list[str]:
    probes = out.get("probes")
    if isinstance(probes, list):
        failed = [str(item.get("name") or "unknown") for item in probes if isinstance(item, dict) and not item.get("ok")]
        if failed:
            return failed
    return ["unknown"]


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
