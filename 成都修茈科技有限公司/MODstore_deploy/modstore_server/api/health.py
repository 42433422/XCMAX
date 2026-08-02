"""Health check routes."""

from __future__ import annotations

import json
import os
import time
from urllib.request import Request, urlopen

from fastapi import APIRouter

from modstore_server.api.dto import HealthResponse
from modstore_server.deploy_context import health_payload

router = APIRouter(tags=["health"])

_SCHEDULER_STATUS_URL = "http://127.0.0.1:9990/api/xcmax/scheduler/health"
_SCHEDULER_STATUS_TIMEOUT_SECONDS = 1.0
_SCHEDULER_STATUS_CACHE_SECONDS = 5.0
_scheduler_status_cache: tuple[float, bool] | None = None


def _background_jobs_enabled() -> bool:
    return os.environ.get("MODSTORE_RUN_BACKGROUND_JOBS", "0") == "1"


def _scheduler_status_url() -> str:
    """Return the private scheduler endpoint, allowing an explicit ops override."""

    return os.environ.get("MODSTORE_SCHEDULER_STATUS_URL", _SCHEDULER_STATUS_URL).strip()


def _scheduler_status_timeout_seconds() -> float:
    try:
        return max(0.1, float(os.environ.get("MODSTORE_SCHEDULER_STATUS_TIMEOUT_SECONDS", "1")))
    except ValueError:
        return _SCHEDULER_STATUS_TIMEOUT_SECONDS


def _scheduler_process_status() -> bool:
    """Read the real scheduler process health with a short, bounded cache.

    Production runs the public API and background jobs in different processes.
    Looking at the API process's in-memory scheduler would therefore report a
    healthy, separately-running scheduler as absent.  This probe deliberately
    targets the scheduler-only control port instead.
    """

    global _scheduler_status_cache

    now = time.monotonic()
    if _scheduler_status_cache is not None:
        checked_at, cached_status = _scheduler_status_cache
        if now - checked_at < _SCHEDULER_STATUS_CACHE_SECONDS:
            return cached_status

    try:
        request = Request(_scheduler_status_url(), headers={"Accept": "application/json"})
        with urlopen(
            request, timeout=_scheduler_status_timeout_seconds()
        ) as response:  # nosec B310
            payload = json.loads(response.read())
        data = payload.get("data") if isinstance(payload, dict) else None
        status = bool(
            isinstance(data, dict)
            and payload.get("success") is True
            and payload.get("ok") is True
            and data.get("scheduler_running") is True
            and data.get("scheduler_healthy") is True
        )
    except Exception:
        status = False

    _scheduler_status_cache = (now, status)
    return status


def _scheduler_status() -> bool | None:
    if not _background_jobs_enabled():
        return _scheduler_process_status()

    try:
        from modstore_server.workflow_scheduler import scheduler_integrity_status

        return bool(scheduler_integrity_status()["ok"])
    except Exception:
        return None


@router.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    ctx = health_payload()
    sch = _scheduler_status()
    return HealthResponse(ok=True, scheduler_running=sch, **ctx)
