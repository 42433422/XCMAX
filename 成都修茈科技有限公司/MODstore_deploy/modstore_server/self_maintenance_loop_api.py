"""Self-maintenance loop runtime status API."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, Query

from modstore_server.api.deps import require_admin
from modstore_server.models import User
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
