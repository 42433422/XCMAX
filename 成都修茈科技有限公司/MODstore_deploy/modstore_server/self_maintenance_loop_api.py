"""Self-maintenance loop runtime status API."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, Query

from modstore_server.api.deps import get_current_user, require_admin
from modstore_server.models import User
from modstore_server.self_maintenance_burnin import (
    get_burnin_status,
    reset_burnin,
    run_burnin_check,
    start_burnin,
)
from modstore_server.self_maintenance_loop_runner import (
    get_self_maintenance_runtime_status,
    record_governance_audit_review,
)

router = APIRouter(prefix="/api/ops/self-maintenance", tags=["ops"])


@router.get("/status", summary="Self-maintenance loop runtime status")
async def get_self_maintenance_status(
    limit: int = Query(default=80, ge=1, le=300),
):
    """Read the scheduler/ledger/memory state consumed by the loop."""

    return get_self_maintenance_runtime_status(limit=limit)


@router.post(
    "/governance-review", summary="Acknowledge self-maintenance governance audit"
)
async def review_self_maintenance_governance(
    body: Dict[str, Any] = Body(default_factory=dict),
    admin_user: User = Depends(require_admin),
):
    """Append a human review audit entry to recover from governance_degraded."""

    return record_governance_audit_review(
        note=str(body.get("note") or ""),
        admin_user_id=getattr(admin_user, "id", None),
    )


@router.get("/burnin", summary="Read self-maintenance burn-in status")
async def get_self_maintenance_burnin_status(
    _user: User = Depends(get_current_user),
):
    """Return the current burn-in state machine status (read-only).

    Any authenticated user may read; admin-only actions are exposed via
    ``/burnin/start``, ``/burnin/reset`` and ``/burnin/check``.
    """

    return get_burnin_status()


@router.post("/burnin/start", summary="Start the 7-day self-maintenance burn-in window")
async def start_self_maintenance_burnin(
    body: Dict[str, Any] = Body(default_factory=dict),
    admin_user: User = Depends(require_admin),
):
    """Start the burn-in window. Errors if a window is already active."""

    started_by = str(body.get("started_by") or "admin")
    return start_burnin(started_by=started_by)


@router.post("/burnin/reset", summary="Reset the self-maintenance burn-in window")
async def reset_self_maintenance_burnin(
    body: Dict[str, Any] = Body(default_factory=dict),
    admin_user: User = Depends(require_admin),
):
    """Clear burn-in state and append the prior run to ``reset_history``."""

    reset_by = str(body.get("reset_by") or "admin")
    return reset_burnin(reset_by=reset_by)


@router.post("/burnin/check", summary="Force-run a burn-in threshold check")
async def check_self_maintenance_burnin(
    _admin_user: User = Depends(require_admin),
):
    """Run ``run_burnin_check`` on demand.

    Does not advance the day counter — the day index is derived from the
    burn-in ``started_at`` timestamp. Use this to verify threshold state
    outside the daily cron cadence.
    """

    return run_burnin_check()
