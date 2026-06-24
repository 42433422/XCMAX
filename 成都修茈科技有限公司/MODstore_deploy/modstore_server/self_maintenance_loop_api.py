"""Self-maintenance loop runtime status API."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, Query

from modstore_server.api.deps import require_admin
from modstore_server.daily_pipeline_lock import self_maintenance_loop_liveness
from modstore_server.models import User
from modstore_server.self_maintenance_loop_runner import (
    get_self_maintenance_runtime_status,
    record_governance_audit_review,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ops/self-maintenance", tags=["ops"])


def _ledger_row_timestamp(row: Any) -> Optional[str]:
    if not isinstance(row, dict):
        return None
    ts = str(
        row.get("completed_at") or row.get("created_at") or row.get("started_at") or ""
    ).strip()
    return ts or None


@router.get("/status", summary="Self-maintenance loop runtime status")
async def get_self_maintenance_status(
    limit: int = Query(default=80, ge=1, le=300),
):
    """Read the scheduler/ledger/memory state consumed by the loop.

    Also attaches ``scheduler_liveness``: complete *或* skip 任一近期有记录即算调度器
    存活;两者长期都没有=停摆(生产曾停 12 天无人知)。stale 时打 WARNING 日志,外部
    探针/日志告警据此发现,无需外部凭据。
    """

    status = get_self_maintenance_runtime_status(limit=limit)

    last_activity = max(
        (
            ts
            for ts in (
                _ledger_row_timestamp(status.get("latest_complete")),
                _ledger_row_timestamp(status.get("latest_skip")),
            )
            if ts
        ),
        default=None,
    )
    liveness = self_maintenance_loop_liveness(last_activity)
    if isinstance(status, dict):
        status["scheduler_liveness"] = liveness
    if liveness.get("is_stale"):
        logger.warning(
            "self_maintenance_loop_stale last_activity=%s age_seconds=%s "
            "threshold_seconds=%s reason=%s",
            liveness.get("last_activity"),
            liveness.get("age_seconds"),
            liveness.get("threshold_seconds"),
            liveness.get("reason"),
        )
    return status


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
