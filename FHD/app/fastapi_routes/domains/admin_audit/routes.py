"""管理员审计日志只读 API（等保证据链辅助，非认证证明）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.application.audit_log_reader import list_audit_log_entries
from app.infrastructure.auth.dependencies import get_logged_in_user

router = APIRouter(prefix="/api/admin", tags=["admin-audit"])


def _require_admin_user(user=Depends(get_logged_in_user)):
    role = str(getattr(user, "role", "") or "").lower()
    if role not in {"admin", "superadmin"}:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=403,
            detail={"message": {"code": "FORBIDDEN", "message": "需要管理员权限"}},
        )
    return user


@router.get("/audit-logs")
def admin_audit_logs(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin=Depends(_require_admin_user),
):
    data = list_audit_log_entries(limit=limit, offset=offset)
    data["requested_by"] = getattr(_admin, "username", None)
    return JSONResponse({"success": True, "data": data})
