"""Submit customer product issues using only the authenticated caller's session."""

from __future__ import annotations

from typing import Any


def submit_client_product_issue(message: str, context: dict[str, Any]) -> dict[str, Any]:
    from starlette.requests import Request

    from app.application.client_product_issue_intake import looks_like_issue_report
    from app.application.employee_runtime.agent_runner import _run_async
    from app.db import HostSessionLocal
    from app.db.models.user import Session as UserSession
    from app.fastapi_routes.xcagi_compat_chat_stream import (
        _classify_and_submit_client_issue_async,
        _client_issue_reply,
    )
    from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError, _bound_actor
    from app.infrastructure.tenant_scope import tenant_scope

    try:
        actor = _bound_actor(context)
        tenant_id = int(context.get("tenant_id") or 0)
        if tenant_id <= 0 or int(actor.tenant_id or 0) != tenant_id:
            raise AgentModAuthorizationError("tenant mismatch")
        if not looks_like_issue_report(message):
            return {"success": False, "message": "原始请求未明确提出产品问题，未提交工单。"}
        with HostSessionLocal() as db:
            session = db.get(UserSession, context["_actor_authorization"]["session_row_id"])
            session_id = str(session.session_id or "") if session is not None else ""
        if not session_id:
            raise AgentModAuthorizationError("session unavailable")
    except (AgentModAuthorizationError, AttributeError, KeyError, TypeError, ValueError):
        return {
            "success": False,
            "message": "需要有效的企业登录身份",
            "error_code": "tool_identity_required",
        }
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/ai/chat",
            "headers": [(b"x-session-id", session_id.encode())],
        }
    )
    with tenant_scope(tenant_id):
        receipt = _run_async(_classify_and_submit_client_issue_async(request, context, message, ""))
    text = _client_issue_reply(receipt)
    if not text:
        return {"success": False, "message": "无法确认这是产品问题，未提交工单。"}
    if receipt.get("state") == "OWNER_ROUTE_UNAVAILABLE":
        return {
            "success": False,
            "message": text,
            "outcome": "unknown",
            "retryable": False,
            "reconciliation_required": True,
        }
    return {
        "success": True,
        "message": text,
        "response": text,
        "data": {
            "state": receipt.get("state"),
            "work_order_id": receipt.get("work_order_id"),
            "owner_ticket_no": receipt.get("owner_ticket_no"),
        },
    }
