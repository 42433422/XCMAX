"""管理员：员工变更申请（审批落盘）。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from modstore_server.api.deps import require_admin
from modstore_server.employee_change_request_service import (
    apply_employee_change_request,
    reject_employee_change_request,
)
from modstore_server.models import EmployeeChangeRequest, User, get_session_factory

router = APIRouter(prefix="/api/admin", tags=["admin-change-requests"])


def _serialize(row: EmployeeChangeRequest) -> Dict[str, Any]:
    import json

    paths: List[str] = []
    approval_required_globs: List[str] = []
    try:
        paths = json.loads(row.target_paths_json or "[]")
        if not isinstance(paths, list):
            paths = []
    except json.JSONDecodeError:
        paths = []
    try:
        approval_required_globs = json.loads(row.approval_required_globs_json or "[]")
        if not isinstance(approval_required_globs, list):
            approval_required_globs = []
    except json.JSONDecodeError:
        approval_required_globs = []
    return {
        "id": int(row.id),
        "source_employee_id": str(row.source_employee_id or ""),
        "change_kind": str(row.change_kind or ""),
        "workspace_root_hint": str(row.workspace_root_hint or ""),
        "target_paths": paths,
        "approval_required_globs": approval_required_globs,
        "diff_summary": str(row.diff_summary or ""),
        "diff_blob": str(row.diff_blob or ""),
        "status": str(row.status or ""),
        "risk_level": str(row.risk_level or ""),
        "approved_by_user_id": int(row.approved_by_user_id) if row.approved_by_user_id else None,
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "applied_at": row.applied_at.isoformat() if row.applied_at else None,
        "rejected_reason": str(row.rejected_reason or ""),
        "error": str(row.error or ""),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/change-requests")
def list_change_requests(
    status: Optional[str] = None,
    limit: int = 50,
    admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    _ = admin_user
    lim = max(1, min(int(limit or 50), 200))
    sf = get_session_factory()
    with sf() as session:
        q = session.query(EmployeeChangeRequest).order_by(EmployeeChangeRequest.id.desc())
        st = (status or "").strip()
        if st:
            q = q.filter(EmployeeChangeRequest.status == st)
        rows = q.limit(lim).all()
        return {"items": [_serialize(r) for r in rows], "count": len(rows)}


@router.get("/change-requests/{change_request_id}")
def get_change_request(
    change_request_id: int,
    admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    _ = admin_user
    if change_request_id <= 0:
        raise HTTPException(400, "invalid id")
    sf = get_session_factory()
    with sf() as session:
        row = session.get(EmployeeChangeRequest, change_request_id)
        if not row:
            raise HTTPException(404, "not found")
        return _serialize(row)


@router.post("/change-requests/{change_request_id}/approve")
def approve_change_request(
    change_request_id: int,
    admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    if change_request_id <= 0:
        raise HTTPException(400, "invalid id")
    out = apply_employee_change_request(change_request_id, int(admin_user.id))
    if not out.get("ok"):
        raise HTTPException(400, out.get("error") or "approve failed")
    return out


@router.post("/change-requests/{change_request_id}/reject")
def reject_change_request(
    change_request_id: int,
    body: Dict[str, Any] = Body(default_factory=dict),
    admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    if change_request_id <= 0:
        raise HTTPException(400, "invalid id")
    reason = str(body.get("reason") or body.get("rejected_reason") or "").strip()
    out = reject_employee_change_request(
        change_request_id,
        rejected_reason=reason or "(no reason)",
        rejected_by_user_id=int(admin_user.id),
    )
    if not out.get("ok"):
        raise HTTPException(400, out.get("error") or "reject failed")
    return {"ok": True}


__all__ = ["router"]
