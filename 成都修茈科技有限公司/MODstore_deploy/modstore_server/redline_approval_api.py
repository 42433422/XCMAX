"""红线审批门控 API：查询、审批、拒绝红线变更请求。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from modstore_server.api.deps import require_admin
from modstore_server.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/redline", tags=["admin-redline"])


def _public_redline_result(result: dict, *, cr_id: int, action: str) -> dict:
    if not bool(result.get("ok")):
        return {
            "ok": False,
            "error": f"redline_{action}_failed",
            "data": {"cr_id": int(cr_id), "status": "failed"},
        }
    return {
        "ok": True,
        "data": {
            "cr_id": int(cr_id),
            "status": "approved" if action == "approve" else "rejected",
        },
    }


class RedlineApprovalRequest(BaseModel):
    comment: str = ""


class RedlineRejectionRequest(BaseModel):
    reason: str = ""


@router.get("/pending")
async def api_pending_redline_requests(_admin: User = Depends(require_admin)):
    from modstore_server.redline_approval_gate import get_pending_redline_requests

    requests = get_pending_redline_requests()
    return {"ok": True, "data": requests, "count": len(requests)}


@router.post("/requests/{cr_id}/approve")
async def api_approve_redline(
    cr_id: int,
    body: RedlineApprovalRequest = RedlineApprovalRequest(),
    admin: User = Depends(require_admin),
):
    from modstore_server.redline_approval_gate import approve_redline_request

    result = approve_redline_request(cr_id, int(admin.id), comment=body.comment)
    return _public_redline_result(result, cr_id=cr_id, action="approve")


@router.post("/requests/{cr_id}/reject")
async def api_reject_redline(
    cr_id: int,
    body: RedlineRejectionRequest = RedlineRejectionRequest(),
    admin: User = Depends(require_admin),
):
    from modstore_server.redline_approval_gate import reject_redline_request

    result = reject_redline_request(cr_id, int(admin.id), reason=body.reason)
    return _public_redline_result(result, cr_id=cr_id, action="reject")


@router.get("/domains")
async def api_redline_domains(_admin: User = Depends(require_admin)):
    from modstore_server.redline_approval_gate import REDLINE_DOMAINS

    return {"ok": True, "data": REDLINE_DOMAINS}


@router.post("/timeout-check")
async def api_check_redline_timeout(_admin: User = Depends(require_admin)):
    from modstore_server.redline_approval_gate import check_redline_timeout

    result = check_redline_timeout()
    return {"ok": True, "data": result}
