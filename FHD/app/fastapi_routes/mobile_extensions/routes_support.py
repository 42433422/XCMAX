"""SupportRoutes: explicit collaborators for one mobile capability."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Table

from app.fastapi_routes.mobile_extensions.models import (
    MobileServiceBridgeRespondBody,
)
from app.fastapi_routes.mobile_extensions.ports import (
    DatabaseCall,
    ImServiceCall,
    MobileBridgeRequestStatusesCall,
    MobileCsSourceIdCall,
    MobileCsSourceNameCall,
    MobilePrincipal,
    NowCall,
    RequireMobileAdminCall,
    SafeUserIdCall,
    SafeUserTextCall,
    UserDependency,
)
from app.mod_sdk.assistant_ssot import dedicated_cs_label
from app.utils.device_system.mobile_api import format_mobile_response, paginate_list
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SupportRoutesPorts:
    mobile_cs_source_id: MobileCsSourceIdCall
    mobile_cs_source_name: MobileCsSourceNameCall
    safe_user_id: SafeUserIdCall
    safe_user_text: SafeUserTextCall
    database: DatabaseCall
    mobile_bridge_request_statuses: MobileBridgeRequestStatusesCall
    now: NowCall
    require_mobile_admin: RequireMobileAdminCall
    im_service: ImServiceCall


class SupportRoutes:
    def __init__(self, ports: SupportRoutesPorts, get_user: UserDependency) -> None:
        self.ports = ports
        self.router = router = APIRouter()

        def _mobile_bridge_request_statuses() -> tuple[str, ...]:
            return ("pending", "processing", "resolved", "closed")

        self._mobile_bridge_request_statuses = _mobile_bridge_request_statuses

        def _persist_mobile_cs_request(
            user: object,
            *,
            message_id: str,
            msg_body: str,
            reply: str,
            backend: str,
            employee_result: dict[str, Any],
        ) -> tuple[int, bool, str]:
            from app.db.models.service_request import ServiceRequest

            username = ports.safe_user_text(user, "username")
            extra = {
                "message_id": message_id,
                "mobile_user_id": ports.safe_user_id(user),
                "username": username,
                "ai_reply": reply,
                "backend": backend,
                "employee_result": employee_result,
            }
            try:
                with ports.database() as db:
                    cast("Table", ServiceRequest.__table__).create(db.get_bind(), checkfirst=True)
                    row = ServiceRequest(
                        source_instance_id=ports.mobile_cs_source_id(user),
                        source_instance_name=ports.mobile_cs_source_name(user),
                        request_type="mobile_ai_customer_service",
                        title=msg_body[:80] or f"{dedicated_cs_label()}咨询",
                        description=msg_body,
                        priority="normal",
                        status="pending",
                        extra_data=json.dumps(extra, ensure_ascii=False),
                    )
                    db.add(row)
                    db.flush()
                    return (int(row.id), True, "")
            except RECOVERABLE_ERRORS as exc:
                logger.warning("mobile cs service request persist skipped: %s", exc)
                return (0, False, "服务请求保存失败")

        self._persist_mobile_cs_request = _persist_mobile_cs_request

        @router.get("/service-bridge/requests", response_model=None)
        async def mobile_service_bridge_requests(
            request: Request,
            status: str | None = None,
            source_instance_id: str | None = None,
            request_type: str | None = None,
            page: int = Query(1, ge=1),
            per_page: int = Query(20, ge=1, le=100),
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )

            with ports.database() as db:
                from app.db.models.service_request import ServiceRequest

                q = db.query(ServiceRequest)
                if status:
                    q = q.filter(ServiceRequest.status == status)
                if source_instance_id:
                    q = q.filter(ServiceRequest.source_instance_id == source_instance_id)
                if request_type:
                    q = q.filter(ServiceRequest.request_type == request_type)
                total = q.count()
                items = (
                    q.order_by(ServiceRequest.created_at.desc())
                    .offset((page - 1) * per_page)
                    .limit(per_page)
                    .all()
                )
                return format_mobile_response(
                    data=paginate_list([r.to_dict() for r in items], total, page, per_page)
                )

        self.mobile_service_bridge_requests = mobile_service_bridge_requests

        @router.put("/service-bridge/requests/{request_id}/respond", response_model=None)
        async def mobile_service_bridge_request_respond(
            request_id: int,
            body: MobileServiceBridgeRespondBody,
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            if request_id <= 0:
                return JSONResponse(
                    format_mobile_response(None, "请求 ID 无效", success=False, code=400),
                    status_code=400,
                )
            if body.status not in ports.mobile_bridge_request_statuses():
                return JSONResponse(
                    format_mobile_response(None, "状态值非法", success=False, code=400),
                    status_code=400,
                )
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )

            try:
                with ports.database() as db:
                    from app.db.models.service_request import ServiceRequest

                    req = db.query(ServiceRequest).filter(ServiceRequest.id == request_id).first()
                    if not req:
                        return JSONResponse(
                            format_mobile_response(None, "请求不存在", success=False, code=404),
                            status_code=404,
                        )
                    req.response = body.response
                    req.responded_by = body.responded_by

                    req.responded_at = ports.now()
                    req.status = body.status
                    db.flush()
                return format_mobile_response(data=req.to_dict())
            except HTTPException:
                raise
            except RECOVERABLE_ERRORS:
                logger.exception("mobile_service_bridge_request_respond")
                return JSONResponse(
                    format_mobile_response(None, "服务响应失败", success=False, code=500),
                    status_code=500,
                )
            except RECOVERABLE_ERRORS:
                logger.exception("mobile service-bridge respond failed")
                return JSONResponse(
                    format_mobile_response(None, "服务响应失败", success=False, code=500),
                    status_code=500,
                )

        self.mobile_service_bridge_request_respond = mobile_service_bridge_request_respond

        @router.get("/im/cs/inbox", response_model=None)
        async def mobile_im_cs_inbox(
            request: Request, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """运营者手机:列出所有企业客户的专属客服会话。"""
            _, err = ports.require_mobile_admin(request, user)
            if err is not None:
                return err

            try:
                with ports.database() as db:
                    items = ports.im_service(db).list_cs_inbox()
                conversations = [
                    {
                        "conversationId": c.get("id"),
                        "customerName": c.get("customer_name")
                        or f"用户{c.get('customer_user_id')}",
                        "lastMessageAt": str(c.get("last_message_at") or ""),
                        "unreadCount": int(c.get("unread_count") or 0),
                    }
                    for c in items
                ]
                return format_mobile_response(data={"conversations": conversations})
            except RECOVERABLE_ERRORS:
                logger.exception("mobile cs inbox failed")
                return JSONResponse(
                    format_mobile_response(None, "客服收件箱加载失败", success=False, code=500),
                    status_code=500,
                )

        self.mobile_im_cs_inbox = mobile_im_cs_inbox

        @router.get("/im/cs/inbox/{conversation_id}/messages", response_model=None)
        async def mobile_im_cs_inbox_messages(
            conversation_id: int, request: Request, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """运营者手机:读某客服会话历史(fromCustomer 区分客户/客服)。"""
            _, err = ports.require_mobile_admin(request, user)
            if err is not None:
                return err

            try:
                with ports.database() as db:
                    svc = ports.im_service(db)
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
            except RECOVERABLE_ERRORS:
                logger.exception("mobile cs inbox messages failed")
                return JSONResponse(
                    format_mobile_response(None, "客服消息加载失败", success=False, code=500),
                    status_code=500,
                )

        self.mobile_im_cs_inbox_messages = mobile_im_cs_inbox_messages

        @router.post("/im/cs/inbox/{conversation_id}/reply", response_model=None)
        async def mobile_im_cs_inbox_reply(
            conversation_id: int,
            body: dict,
            request: Request,
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            """运营者手机:以「企业专属客服」身份回复客户。"""
            _, err = ports.require_mobile_admin(request, user)
            if err is not None:
                return err
            text = str(body.get("body") or "").strip()
            if not text:
                return JSONResponse(
                    format_mobile_response(None, "消息不能为空", success=False, code=400),
                    status_code=400,
                )

            try:
                with ports.database() as db:
                    result = ports.im_service(db).cs_reply(conversation_id, text)
                sent = result.get("message") or {}
                return format_mobile_response(
                    data={
                        "messageId": str(sent.get("id") or ""),
                        "timestamp": str(sent.get("created_at") or ""),
                    }
                )
            except (ValueError, PermissionError):
                return JSONResponse(
                    format_mobile_response(None, "回复内容无效", success=False, code=400),
                    status_code=400,
                )
            except RECOVERABLE_ERRORS:
                logger.exception("mobile cs inbox reply failed")
                return JSONResponse(
                    format_mobile_response(None, "客服回复失败", success=False, code=500),
                    status_code=500,
                )

        self.mobile_im_cs_inbox_reply = mobile_im_cs_inbox_reply
