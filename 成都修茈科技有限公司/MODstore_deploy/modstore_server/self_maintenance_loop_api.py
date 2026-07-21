"""Self-maintenance loop runtime status API."""

from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, Query

from modstore_server.api.deps import require_admin
from modstore_server.models import User
from modstore_server.self_maintenance_loop_runner import (
    get_self_maintenance_runtime_status,
    record_governance_audit_review,
    run_self_maintenance_loop,
)

router = APIRouter(prefix="/api/ops/self-maintenance", tags=["ops"])


@router.get("/status", summary="Self-maintenance loop runtime status")
async def get_self_maintenance_status(
    limit: int = Query(default=80, ge=1, le=300),
):
    """Read the scheduler/ledger/memory state consumed by the loop."""

    return get_self_maintenance_runtime_status(limit=limit)


@router.post("/run", summary="Force-run one self-maintenance loop transaction")
async def force_run_self_maintenance_loop(
    body: Dict[str, Any] = Body(default_factory=dict),
    admin_user: User = Depends(require_admin),
):
    """Admin break-glass: run one loop cycle now (force=True bypasses cooldown gate)."""

    reason = str(body.get("reason") or "admin_force_run").strip() or "admin_force_run"
    # Force break-glass: do not stall on a busy Mac codex currentTask.
    prev_busy = os.environ.get("MODSTORE_SELF_MAINTENANCE_ALLOW_BUSY_DEVICE")
    prev_wait = os.environ.get("MODSTORE_SELF_MAINTENANCE_DEVICE_ONLINE_WAIT_SEC")
    os.environ["MODSTORE_SELF_MAINTENANCE_ALLOW_BUSY_DEVICE"] = "1"
    os.environ["MODSTORE_SELF_MAINTENANCE_DEVICE_ONLINE_WAIT_SEC"] = (
        prev_wait if (prev_wait or "").strip() else "15"
    )
    try:
        result = run_self_maintenance_loop(
            triggered_by=f"admin:{getattr(admin_user, 'id', '') or 'unknown'}",
            force=True,
            reason=reason,
        )
    finally:
        if prev_busy is None:
            os.environ.pop("MODSTORE_SELF_MAINTENANCE_ALLOW_BUSY_DEVICE", None)
        else:
            os.environ["MODSTORE_SELF_MAINTENANCE_ALLOW_BUSY_DEVICE"] = prev_busy
        if prev_wait is None:
            os.environ.pop("MODSTORE_SELF_MAINTENANCE_DEVICE_ONLINE_WAIT_SEC", None)
        else:
            os.environ["MODSTORE_SELF_MAINTENANCE_DEVICE_ONLINE_WAIT_SEC"] = prev_wait
    return {"ok": True, "result": result}


@router.post("/governance-review", summary="Acknowledge self-maintenance governance audit")
async def review_self_maintenance_governance(
    body: Dict[str, Any] = Body(default_factory=dict),
    admin_user: User = Depends(require_admin),
):
    """Append a human review audit entry to recover from governance_degraded."""

    return record_governance_audit_review(
        note=str(body.get("note") or ""),
        admin_user_id=getattr(admin_user, "id", None),
    )
