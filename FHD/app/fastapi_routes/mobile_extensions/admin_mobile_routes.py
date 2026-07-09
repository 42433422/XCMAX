"""Mobile 管理端员工 / 首页 / IM 客服收件箱 routes (split from mobile_api_extensions).

Included into ``extension_router``; handlers and helpers are re-exported from
``mobile_api_extensions`` for tests and patch compatibility.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.fastapi_routes.mobile_api import get_mobile_user
from app.fastapi_routes.mobile_extensions import _ext as mext
from app.utils.mobile_api import format_mobile_response

logger = logging.getLogger(__name__)

admin_mobile_router = APIRouter()

from app.fastapi_routes.mobile_extensions.constants import ADMIN_MOBILE_FEATURES

# ── 管理端 ──


@admin_mobile_router.get("/admin/employees")
async def mobile_admin_employees(request: Request, user=Depends(get_mobile_user)):
    _, err = mext._require_mobile_admin(request, user)
    if err is not None:
        return err
    market_profiles, market_connected, market_error = await mext._load_market_ai_employee_profile_index()
    uid = mext._mobile_request_user_id(request, user)
    im_summary: dict[str, dict[str, Any]] = {}
    if uid > 0:
        try:
            from app.application.im_app_service import ImApplicationService
            from app.db import SessionLocal

            db = SessionLocal()
            try:
                raw_items = mext._admin_employee_items(
                    market_profiles, market_connected=market_connected
                )
                im_summary = ImApplicationService(db).employee_im_summary(uid, raw_items)
            finally:
                db.close()
        except mext.RECOVERABLE_ERRORS:
            logger.debug("employee_im_summary skipped for /admin/employees", exc_info=True)
    items = mext._admin_employee_items(
        market_profiles, market_connected=market_connected, im_summary=im_summary
    )
    return format_mobile_response(
        data={
            "items": items,
            "count": len(items),
            "market_connected": market_connected,
            "market_profile_count": len(market_profiles),
            "market_error": market_error,
        }
    )


@admin_mobile_router.get("/admin/features")
async def mobile_admin_features(request: Request, user=Depends(get_mobile_user)):
    _, err = mext._require_mobile_admin(request, user)
    if err is not None:
        return err
    return format_mobile_response(
        data={"items": ADMIN_MOBILE_FEATURES, "count": len(ADMIN_MOBILE_FEATURES)}
    )


# ── 管理端客服收件箱(企业客户↔企业专属客服,手机 Bearer + admin 守卫)──


@admin_mobile_router.get("/im/cs/inbox")
async def mobile_im_cs_inbox(request: Request, user=Depends(get_mobile_user)):
    """运营者手机:列出所有企业客户的专属客服会话。"""
    _, err = mext._require_mobile_admin(request, user)
    if err is not None:
        return err
    from app.application.im_app_service import ImApplicationService
    from app.db.session import get_db

    try:
        with get_db() as db:
            items = ImApplicationService(db).list_cs_inbox()
        conversations = [
            {
                "conversationId": c.get("id"),
                "customerName": c.get("customer_name") or f"用户{c.get('customer_user_id')}",
                "lastMessageAt": str(c.get("last_message_at") or ""),
                "unreadCount": int(c.get("unread_count") or 0),
            }
            for c in items
        ]
        return format_mobile_response(data={"conversations": conversations})
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile cs inbox failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


@admin_mobile_router.get("/im/cs/inbox/{conversation_id}/messages")
async def mobile_im_cs_inbox_messages(
    conversation_id: int, request: Request, user=Depends(get_mobile_user)
):
    """运营者手机:读某客服会话历史(fromCustomer 区分客户/客服)。"""
    _, err = mext._require_mobile_admin(request, user)
    if err is not None:
        return err
    from app.application.im_app_service import ImApplicationService
    from app.db.session import get_db

    try:
        with get_db() as db:
            svc = ImApplicationService(db)
            cs_id = int(svc.enterprise_cs_user_id() or 0)
            raw = svc.cs_inbox_messages(conversation_id)
        messages = [
            {
                "messageId": str(m.get("id") or ""),
                "fromCustomer": int(m.get("sender_user_id") or 0) != cs_id,
                "senderName": str(m.get("sender_display_name") or ""),
                "body": str(m.get("body") or ""),
                "timestamp": str(m.get("created_at") or ""),
            }
            for m in raw
        ]
        return format_mobile_response(data={"messages": messages})
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile cs inbox messages failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


@admin_mobile_router.post("/im/cs/inbox/{conversation_id}/reply")
async def mobile_im_cs_inbox_reply(
    conversation_id: int, body: dict, request: Request, user=Depends(get_mobile_user)
):
    """运营者手机:以「企业专属客服」身份回复客户。"""
    _, err = mext._require_mobile_admin(request, user)
    if err is not None:
        return err
    text = str(body.get("body") or "").strip()
    if not text:
        return JSONResponse(
            format_mobile_response(None, "消息不能为空", success=False, code=400), status_code=400
        )
    from app.application.im_app_service import ImApplicationService
    from app.db.session import get_db

    try:
        with get_db() as db:
            result = ImApplicationService(db).cs_reply(conversation_id, text)
        sent = result.get("message") or {}
        return format_mobile_response(
            data={
                "messageId": str(sent.get("id") or ""),
                "timestamp": str(sent.get("created_at") or ""),
            }
        )
    except (ValueError, PermissionError) as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=400), status_code=400
        )
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile cs inbox reply failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


@admin_mobile_router.get("/admin/home")
async def mobile_admin_home(request: Request, user=Depends(get_mobile_user)):
    meta, err = mext._require_mobile_admin(request, user)
    if err is not None:
        return err
    market_profiles, market_connected, market_error = await mext._load_market_ai_employee_profile_index()
    employees = mext._admin_employee_items(market_profiles, market_connected=market_connected)
    # 把员工与老板的 direct IM 会话摘要合并进员工项，让 App 在现有员工列表里直接看到/点进 IM 会话。
    # employee_im_summary 会自动为尚无 IM 用户/会话的员工 ensure 虚拟用户 + 创建空 direct 会话，
    # 确保老板首次点击员工聊天页时 im_conv_id > 0，前端能正常走 IM 消息通道。
    uid = mext._mobile_request_user_id(request, user)
    im_summary: dict[str, dict[str, Any]] = {}
    if uid > 0 and employees:
        try:
            from app.application.im_app_service import ImApplicationService
            from app.db import SessionLocal

            db = SessionLocal()
            try:
                im_summary = ImApplicationService(db).employee_im_summary(uid, employees)
            finally:
                db.close()
        except mext.RECOVERABLE_ERRORS:
            logger.debug("employee_im_summary skipped", exc_info=True)
    employees = mext._admin_employee_items(
        market_profiles, market_connected=market_connected, im_summary=im_summary
    )
    return format_mobile_response(
        data={
            "account_kind": meta.get("account_kind") or "admin",
            "employees": employees,
            "employee_count": len(employees),
            "features": ADMIN_MOBILE_FEATURES,
            "feature_count": len(ADMIN_MOBILE_FEATURES),
            "market_connected": market_connected,
            "market_profile_count": len(market_profiles),
            "market_error": market_error,
        }
    )
