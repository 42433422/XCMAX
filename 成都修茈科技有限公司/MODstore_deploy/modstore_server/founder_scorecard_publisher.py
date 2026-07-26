"""Scheduled publisher for the public founder-autonomy scorecard.

The admin cockpit remains session-gated for humans.  This worker uses two
independent credentials for unattended refreshes:

* a short-lived MODstore admin bearer for reading live evidence; and
* the shared autonomy webhook token for authorising the FHD publish action.

No credential or internal evidence payload is written to the public file.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


def _fhd_base_url() -> str:
    return (
        str(
            os.environ.get("MODSTORE_FOUNDER_SCORECARD_FHD_BASE_URL")
            or os.environ.get("MODSTORE_FHD_LOCAL_BASE_URL")
            or "http://127.0.0.1:5100"
        )
        .strip()
        .rstrip("/")
    )


def _autonomy_token() -> str:
    return str(
        os.environ.get("AUTONOMY_WEBHOOK_TOKEN")
        or os.environ.get("MODSTORE_OPS_INGEST_TOKEN")
        or ""
    ).strip()


def _timeout_seconds() -> float:
    try:
        return max(
            15.0,
            min(
                180.0,
                float(os.environ.get("MODSTORE_FOUNDER_SCORECARD_TIMEOUT_SECONDS", "90")),
            ),
        )
    except ValueError:
        return 90.0


def _int_env(name: str, default: int, *, minimum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, value)


def _issue_market_admin_bearer() -> str:
    """Mint a short-lived machine bearer without depending on a human password."""
    from modstore_server.auth_service import create_access_token
    from modstore_server.models import User, get_session_factory

    session_factory = get_session_factory()
    with session_factory() as session:
        admin = session.query(User).filter(User.is_admin.is_(True)).order_by(User.id.asc()).first()
        if admin is None:
            raise RuntimeError("founder scorecard refresh has no market admin identity")
        user_id = int(admin.id)
        username = str(admin.username or "").strip()
    if user_id <= 0 or not username:
        raise RuntimeError("founder scorecard refresh has invalid market admin identity")
    return create_access_token(
        user_id,
        username,
        is_admin=True,
        expires_delta=timedelta(minutes=10),
        actor="founder-scorecard-publisher",
    )


def publish_founder_scorecard() -> dict[str, Any]:
    """Refresh the seven dimensions and atomically publish the public subset.

    Failures raise so ``scheduler_runtime`` records a failed job instead of
    treating a login error or partial publication as a successful heartbeat.
    """

    autonomy_token = _autonomy_token()
    if not autonomy_token:
        raise RuntimeError("founder scorecard refresh has no autonomy webhook token")
    market_bearer = _issue_market_admin_bearer()
    if not market_bearer:
        raise RuntimeError("founder scorecard refresh has no market admin bearer")

    request = urllib.request.Request(
        f"{_fhd_base_url()}/api/xcmax/ops/founder-autonomy/refresh-internal",
        data=b"{}",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {market_bearer}",
            "Content-Type": "application/json",
            "User-Agent": "MODstore-founder-scorecard/1.0",
            "X-Autonomy-Token": autonomy_token,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_timeout_seconds()) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))

    if not isinstance(payload, dict) or not payload.get("success"):
        raise RuntimeError("founder scorecard refresh endpoint rejected publication")
    snapshot = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    dimensions = snapshot.get("dimensions")
    publication = payload.get("publication") if isinstance(payload.get("publication"), dict) else {}
    if not isinstance(dimensions, list) or len(dimensions) != 7:
        raise RuntimeError("founder scorecard refresh returned incomplete dimensions")
    if not publication.get("ok"):
        raise RuntimeError("founder scorecard public projection was not fully published")

    return {
        "ok": True,
        "generated_at": str(snapshot.get("generated_at") or ""),
        "overall_progress": int(snapshot.get("overall_progress") or 0),
        "dimension_count": len(dimensions),
        "published_target_count": len(publication.get("written") or []),
    }


def register_founder_scorecard_job(scheduler: Any) -> None:
    """Register the tracked production refresher without growing the core scheduler."""
    from modstore_server.scheduler_runtime import track_job_run

    def _refresh() -> None:
        try:
            with track_job_run("founder_scorecard_refresh"):
                result = publish_founder_scorecard()
            logger.info(
                "founder scorecard refreshed generated_at=%s overall=%s targets=%s",
                result.get("generated_at"),
                result.get("overall_progress"),
                result.get("published_target_count"),
            )
        except Exception:
            logger.exception("founder scorecard refresh failed")

    scheduler.add_job(
        _refresh,
        IntervalTrigger(
            minutes=_int_env("MODSTORE_FOUNDER_SCORECARD_REFRESH_MINUTES", 15, minimum=5)
        ),
        id="founder_scorecard_refresh",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=60),
        misfire_grace_time=_int_env(
            "MODSTORE_SCHEDULER_BUSINESS_MISFIRE_GRACE_SECONDS",
            3600,
            minimum=60,
        ),
        coalesce=True,
        max_instances=1,
    )


__all__ = ["publish_founder_scorecard", "register_founder_scorecard_job"]
