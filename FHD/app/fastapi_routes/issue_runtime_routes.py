"""Customer-visible shared-host repair delivery acknowledgement."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.application.shared_issue_runtime import pending_issues, report_issue

router = APIRouter(tags=["customer-issue-delivery"])


class RuntimeDecision(BaseModel):
    confirmed: bool = False
    note: str = Field(default="", max_length=2000)


@router.get("/issue-runtime")
async def list_issue_runtime(request: Request):
    return {"success": True, "data": await pending_issues(request)}


@router.post("/issue-runtime/{ticket_id}")
async def submit_issue_runtime(ticket_id: int, body: RuntimeDecision, request: Request):
    return {
        "success": True,
        "data": await report_issue(
            request,
            ticket_id,
            confirmed=body.confirmed,
            note=body.note,
        ),
    }


@router.post("/receipts/retry")
async def retry_current_delivery_receipts(request: Request):
    from app.application.mod_delivery_receipt_outbox import retry_delivery_receipts
    from app.fastapi_routes.private_mod_delivery_context import _private_delivery_market_token
    from app.infrastructure.auth.dependencies import get_logged_in_user

    get_logged_in_user(request)
    token = await _private_delivery_market_token(request)
    if not token:
        raise HTTPException(401, "请登录市场账号后同步交付回执")
    return {"success": True, "data": await retry_delivery_receipts(request, token)}
