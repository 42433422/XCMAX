"""ContactRoutes: explicit collaborators for one mobile capability."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse

from app.fastapi_routes.mobile_extensions.ports import (
    DatabaseCall,
    FixedContactsCall,
    ImServiceCall,
    MobileGroupModeCall,
    MobilePrincipal,
    MobileRequestUserIdCall,
    ProcessCsMessageCall,
    UserDependency,
)
from app.utils.device_system.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContactRoutesPorts:
    mobile_group_mode: MobileGroupModeCall
    fixed_contacts: FixedContactsCall
    mobile_request_user_id: MobileRequestUserIdCall
    im_service: ImServiceCall
    database: DatabaseCall
    process_cs_message: ProcessCsMessageCall


class ContactRoutes:
    def __init__(self, ports: ContactRoutesPorts, get_user: UserDependency) -> None:
        self.ports = ports
        self.router = router = APIRouter()

        @router.get("/contacts/fixed", response_model=None)
        async def get_mobile_fixed_contacts(
            request: Request, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """返回手机端联系人固定区(按端 SSOT 派生)。

            top/bottom 以平台员工为界:渲染顺序 = top + 平台员工(动态) + bottom。
            管理端不含专属客服(由 surface SSOT 自动 gating);两端均含小C与超级员工。
            """
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )

            return format_mobile_response(
                data=ports.fixed_contacts(ports.mobile_group_mode(request))
            )

        self.get_mobile_fixed_contacts = get_mobile_fixed_contacts

        @router.get("/cs/info", response_model=None)
        async def get_cs_info(
            request: Request, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """返回当前用户的小C/智能客服信息。"""
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )
            return format_mobile_response(
                data={
                    "cs_available": True,
                    "cs_name": "企业专属客服",
                    "cs_avatar": None,
                    "cs_online": True,
                    "backend": "enterprise-cs",
                }
            )

        self.get_cs_info = get_cs_info

        @router.post("/cs/messages", response_model=None)
        async def post_cs_message(
            request: Request,
            body: dict,
            background_tasks: BackgroundTasks,
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            """发送消息到企业桌面端同源智能客服通道。"""
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )
            msg_body = str(body.get("body", "") or "").strip()
            if not msg_body:
                return JSONResponse(
                    format_mobile_response(None, "消息不能为空", success=False, code=400),
                    status_code=400,
                )
            # 专属客服 = 企业客户↔运营者管理端的真实 IM 通道(与桌面端同源 enterprise-cs),不再复用小C LLM。
            # 客户消息写入 IM,运营者在管理端「客服收件箱」收到并以「企业专属客服」身份回复。
            uid = ports.mobile_request_user_id(request, user)
            if uid <= 0:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )

            try:
                with ports.database() as db:
                    svc = ports.im_service(db)
                    cs = svc._ensure_enterprise_dedicated_cs_user()
                    if cs is None or int(cs.id) == uid:
                        return JSONResponse(
                            format_mobile_response(None, "客服通道不可用", success=False, code=500),
                            status_code=500,
                        )
                    conv = svc.get_or_create_direct(uid, int(cs.id))
                    result = svc.send_message(int(conv["id"]), uid, msg_body, origin="customer")
                    conversation_id = int(conv["id"])
                sent = result.get("message") or {}

                if background_tasks is not None:
                    background_tasks.add_task(
                        ports.process_cs_message,
                        conversation_id,
                        uid,
                        int(sent.get("id") or 0),
                        msg_body,
                    )
                return format_mobile_response(
                    data={
                        "message_id": str(sent.get("id") or ""),
                        # AI/人工均写回同一 IM；客户端继续按既有轮询刷新，无需打新包。
                        "reply": "",
                        "backend": "enterprise-cs",
                        "timestamp": str(sent.get("created_at") or ""),
                    }
                )
            except RECOVERABLE_ERRORS:
                logger.exception("mobile cs send via IM failed")
                return JSONResponse(
                    format_mobile_response(None, "客服通道暂不可用", success=False, code=500),
                    status_code=500,
                )

        self.post_cs_message = post_cs_message

        @router.get("/cs/messages", response_model=None)
        async def get_cs_messages(
            request: Request,
            since: str | None = None,
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            """拉取小C/智能客服消息。"""
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )
            # 从 enterprise-cs 真实 IM 会话拉取消息(客户发的 + 运营者以「企业专属客服」回复的)。

            uid = ports.mobile_request_user_id(request, user)
            if uid <= 0:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )
            error = ""
            messages: list[dict[str, Any]] = []
            try:
                with ports.database() as db:
                    svc = ports.im_service(db)
                    cs = svc._ensure_enterprise_dedicated_cs_user()
                    if cs is not None and int(cs.id) != uid:
                        conv = svc.get_or_create_direct(uid, int(cs.id))
                        raw = svc.list_messages(int(conv["id"]), uid, limit=100)
                        messages = [
                            {
                                "messageId": str(m.get("id") or ""),
                                # 发送者是自己=user,否则=客服(运营者以 enterprise-cs 身份回复)。
                                "sender": (
                                    "user" if int(m.get("sender_user_id") or 0) == uid else "cs"
                                ),
                                "body": str(m.get("body") or ""),
                                "timestamp": str(m.get("created_at") or ""),
                            }
                            for m in raw
                        ]
            except RECOVERABLE_ERRORS as exc:
                logger.warning("mobile cs message history (IM) unavailable: %s", exc)
                error = "客服消息历史暂不可用"
            if since:
                messages = [m for m in messages if str(m.get("timestamp") or "") > since]
            return format_mobile_response(data={"messages": messages, "persist_error": error})

        self.get_cs_messages = get_cs_messages
