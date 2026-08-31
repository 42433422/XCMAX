"""Admin-only enterprise customer-service inbox routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse

from app.application.im_app_service import ImApplicationService, ensure_im_tables
from app.db import HostSessionLocal, get_host_engine
from app.infrastructure.auth.dependencies import CurrentUser, require_identified_user
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["im-v0"])
_schema_ready = False
_IM_UNAVAILABLE = "即时通信服务暂时不可用，请稍后重试"


def _ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    ensure_im_tables(get_host_engine())
    _schema_ready = True


def _uid(user: CurrentUser) -> int:
    if user.user_id is None:
        raise ValueError("user_id required")
    return int(user.user_id)


def _is_admin_customer_service_session(request: Request, db: Any) -> bool:
    try:
        from app.db.models.user import Session as UserSession
        from app.infrastructure.auth.dependencies import session_id_from_request

        sid = session_id_from_request(request)
        if not sid:
            return False
        row = db.query(UserSession).filter(UserSession.session_id == sid).first()
    except RECOVERABLE_ERRORS:
        return False
    return bool(
        row is not None
        and str(getattr(row, "account_kind", "") or "").strip() == "admin"
        and bool(getattr(row, "market_is_admin", False))
    )


@router.get("/api/im/cs/inbox")
def im_cs_inbox(request: Request, user: CurrentUser = Depends(require_identified_user)):
    """List all customer conversations in the admin CS inbox."""
    _ensure_schema()
    db = HostSessionLocal()
    try:
        if not _is_admin_customer_service_session(request, db):
            return JSONResponse(
                {"success": False, "message": "需要管理端客服会话"}, status_code=403
            )
        items = ImApplicationService(db).list_cs_inbox()
        return {"success": True, "conversations": items}
    except RECOVERABLE_ERRORS:
        logger.exception("im_cs_inbox")
        return JSONResponse({"success": False, "message": _IM_UNAVAILABLE}, status_code=500)
    finally:
        db.close()


@router.get("/api/im/cs/inbox/{conversation_id}/messages")
def im_cs_inbox_messages(
    conversation_id: int,
    request: Request,
    user: CurrentUser = Depends(require_identified_user),
):
    """Read one enterprise customer-service conversation."""
    _ensure_schema()
    db = HostSessionLocal()
    try:
        if not _is_admin_customer_service_session(request, db):
            return JSONResponse(
                {"success": False, "message": "需要管理端客服会话"}, status_code=403
            )
        messages = ImApplicationService(db).cs_inbox_messages(conversation_id)
        return {"success": True, "messages": messages}
    except RECOVERABLE_ERRORS:
        logger.exception("im_cs_inbox_messages")
        return JSONResponse({"success": False, "message": _IM_UNAVAILABLE}, status_code=500)
    finally:
        db.close()


@router.post("/api/im/cs/inbox/{conversation_id}/reply")
def im_cs_inbox_reply(
    conversation_id: int,
    request: Request,
    body: dict = Body(default_factory=dict),
    user: CurrentUser = Depends(require_identified_user),
):
    """Reply as the dedicated CS identity and switch to human mode."""
    _ensure_schema()
    db = HostSessionLocal()
    try:
        if not _is_admin_customer_service_session(request, db):
            return JSONResponse(
                {"success": False, "message": "需要管理端客服会话"}, status_code=403
            )
        text = str(body.get("body") or "").strip()
        if not text:
            return JSONResponse({"success": False, "message": "消息不能为空"}, status_code=400)
        from app.application.enterprise_cs_automation import (
            EnterpriseCsAutomationService,
        )

        operator_user_id = _uid(user)
        EnterpriseCsAutomationService(db).note_manual_reply(
            conversation_id, operator_user_id=operator_user_id
        )
        result = ImApplicationService(db).cs_reply(
            conversation_id,
            text,
            origin="manual",
            operator_user_id=operator_user_id,
        )
        return {"success": True, **result}
    except (ValueError, PermissionError):
        return JSONResponse({"success": False, "message": "消息参数无效"}, status_code=400)
    except RECOVERABLE_ERRORS:
        logger.exception("im_cs_inbox_reply")
        return JSONResponse({"success": False, "message": _IM_UNAVAILABLE}, status_code=500)
    finally:
        db.close()


@router.post("/api/im/cs/inbox/{conversation_id}/mode")
def im_cs_inbox_mode(
    conversation_id: int,
    request: Request,
    body: dict = Body(default_factory=dict),
    user: CurrentUser = Depends(require_identified_user),
):
    """Switch an inbox conversation between AI and human handling."""
    _ensure_schema()
    db = HostSessionLocal()
    try:
        if not _is_admin_customer_service_session(request, db):
            return JSONResponse(
                {"success": False, "message": "需要管理端客服会话"}, status_code=403
            )
        from app.application.enterprise_cs_automation import (
            EnterpriseCsAutomationService,
        )

        state = EnterpriseCsAutomationService(db).set_mode(
            conversation_id,
            str(body.get("mode") or "").strip().lower(),
            operator_user_id=_uid(user),
            reason=str(body.get("reason") or "管理员人工接管"),
        )
        return {"success": True, "state": state}
    except ValueError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=400)
    except RECOVERABLE_ERRORS:
        logger.exception("im_cs_inbox_mode")
        return JSONResponse({"success": False, "message": _IM_UNAVAILABLE}, status_code=500)
    finally:
        db.close()
