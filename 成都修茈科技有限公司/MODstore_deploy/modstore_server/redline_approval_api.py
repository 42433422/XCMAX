"""红线审批门控 API：查询、审批、拒绝红线变更请求。"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/redline", tags=["admin-redline"])


class RedlineApprovalRequest(BaseModel):
    admin_user_id: int = 0
    comment: str = ""


class RedlineRejectionRequest(BaseModel):
    admin_user_id: int = 0
    reason: str = ""


@router.get("/pending")
async def api_pending_redline_requests():
    from modstore_server.redline_approval_gate import get_pending_redline_requests

    requests = get_pending_redline_requests()
    return {"ok": True, "data": requests, "count": len(requests)}


@router.post("/requests/{cr_id}/approve")
async def api_approve_redline(cr_id: int, body: RedlineApprovalRequest = RedlineApprovalRequest()):
    from modstore_server.redline_approval_gate import approve_redline_request

    result = approve_redline_request(cr_id, body.admin_user_id, comment=body.comment)
    return {"ok": result.get("ok", False), "data": result}


@router.post("/requests/{cr_id}/reject")
async def api_reject_redline(cr_id: int, body: RedlineRejectionRequest = RedlineRejectionRequest()):
    from modstore_server.redline_approval_gate import reject_redline_request

    result = reject_redline_request(cr_id, body.admin_user_id, reason=body.reason)
    return {"ok": result.get("ok", False), "data": result}


@router.get("/domains")
async def api_redline_domains():
    from modstore_server.redline_approval_gate import REDLINE_DOMAINS

    return {"ok": True, "data": REDLINE_DOMAINS}


@router.post("/timeout-check")
async def api_check_redline_timeout():
    from modstore_server.redline_approval_gate import check_redline_timeout

    result = check_redline_timeout()
    return {"ok": True, "data": result}
