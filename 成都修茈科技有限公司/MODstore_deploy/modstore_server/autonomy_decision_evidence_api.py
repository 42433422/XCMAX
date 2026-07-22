"""Admin-only, read-only alignment and veto evidence API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from modstore_server.api.deps import require_admin
from modstore_server.autonomy_decision_audit import build_autonomy_decision_evidence
from modstore_server.models import User
from modstore_server.redline_approval_gate import get_pending_redline_requests

router = APIRouter(prefix="/api/admin/autonomy", tags=["admin-alignment"])


@router.get("/evidence")
def autonomy_decision_evidence(
    window_days: int = Query(30, ge=1, le=3650),
    limit: int = Query(100, ge=1, le=1000),
    _admin_user: User = Depends(require_admin),
) -> dict[str, Any]:
    """Return aggregate proof and bounded audit rows; never mutates veto state."""

    _ = _admin_user
    data = build_autonomy_decision_evidence(window_days=window_days, limit=limit)
    data["veto_channel"] = {
        "available": True,
        "pending_count": len(get_pending_redline_requests()),
        "pending_read_endpoint": "/api/admin/redline/pending",
        "decision_contract": "existing redline approve/reject endpoints",
        "writes_added_by_evidence_api": False,
    }
    return {"ok": True, "data": data}


__all__ = ["router"]
