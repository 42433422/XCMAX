"""RelayRoutes: explicit collaborators for one mobile capability."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.fastapi_routes.mobile_extensions.models import (
    RelayDesktopCompleteBody,
    RelayDesktopPollBody,
    RelayDesktopRegisterBody,
    RelayDesktopRenewBody,
    RelayMobileBindAccountBody,
    RelayTaskCreateBody,
)
from app.fastapi_routes.mobile_extensions.ports import (
    MobilePrincipal,
    MobileRelayServiceFactory,
    MobileUserIdentityCall,
    MobileUserPublicDictCall,
    PairingRateAllowedCall,
    RelayMobileAuthPayloadCall,
    UserDependency,
)
from app.utils.device_system.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RelayRoutesPorts:
    pairing_rate_allowed: PairingRateAllowedCall
    mobile_relay_service: MobileRelayServiceFactory
    mobile_user_identity: MobileUserIdentityCall
    mobile_user_public_dict: MobileUserPublicDictCall
    relay_mobile_auth_payload: RelayMobileAuthPayloadCall


class RelayRoutes:
    def __init__(self, ports: RelayRoutesPorts, get_user: UserDependency) -> None:
        self.ports = ports
        self.router = router = APIRouter()

        @router.post("/relay/desktop/register", response_model=None)
        async def mobile_relay_desktop_register(
            body: RelayDesktopRegisterBody, request: Request
        ) -> object:
            """Desktop runtime registers a long-lived cloud relay binding session."""
            if not body.device_id.strip():
                return JSONResponse(
                    format_mobile_response(None, "设备身份无效", success=False, code=400),
                    status_code=400,
                )
            from app.security.lan_ip import get_client_ip

            trusted = os.environ.get("LAN_TRUSTED_PROXIES", "").split(",")
            ip = get_client_ip(request.scope, trusted)
            if not ip or not ports.pairing_rate_allowed(
                ip, "mobile-relay-desktop-register", 100, 86400
            ):
                return JSONResponse(
                    format_mobile_response(None, "注册过于频繁", success=False, code=429),
                    status_code=429,
                )
            try:
                data = ports.mobile_relay_service().register_desktop(
                    label=body.label,
                    device_id=body.device_id,
                    capabilities=body.capabilities,
                    relay_base_url=body.relay_base_url,
                )
                return format_mobile_response(data=data)
            except RECOVERABLE_ERRORS:
                logger.exception("mobile_relay_desktop_register")
                return JSONResponse(
                    format_mobile_response(None, "桌面端注册失败", success=False, code=500),
                    status_code=500,
                )

        self.mobile_relay_desktop_register = mobile_relay_desktop_register

        @router.post("/relay/desktop/renew", response_model=None)
        async def mobile_relay_desktop_renew(
            body: RelayDesktopRenewBody, request: Request
        ) -> object:
            from app.security.lan_ip import get_client_ip

            trusted = os.environ.get("LAN_TRUSTED_PROXIES", "").split(",")
            ip = get_client_ip(request.scope, trusted)
            if not ip or not ports.pairing_rate_allowed(
                ip, "mobile-relay-desktop-renew", 1000, 86400
            ):
                return JSONResponse(
                    format_mobile_response(None, "刷新过于频繁", success=False, code=429),
                    status_code=429,
                )
            try:
                data = ports.mobile_relay_service().renew_desktop_pairing(
                    relay_id=body.relay_id, desktop_token=body.desktop_token
                )
                if data:
                    return format_mobile_response(data=data)
                return JSONResponse(
                    format_mobile_response(None, "设备不存在或已撤销", success=False, code=404),
                    status_code=404,
                )
            except RECOVERABLE_ERRORS:
                logger.exception("mobile_relay_desktop_renew")
                return JSONResponse(
                    format_mobile_response(None, "设备码刷新失败", success=False, code=500),
                    status_code=500,
                )

        self.mobile_relay_desktop_renew = mobile_relay_desktop_renew

        @router.post("/relay/mobile/bind-account", response_model=None)
        async def mobile_relay_bind_account(
            body: RelayMobileBindAccountBody, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            uid, username = ports.mobile_user_identity(user)
            if uid <= 0 or not getattr(user, "is_active", False):
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )
            code = body.pairing_code.strip()
            if len(code) != 6 or not code.isdigit():
                return JSONResponse(
                    format_mobile_response(None, "设备码无效", success=False, code=400),
                    status_code=400,
                )
            if not ports.pairing_rate_allowed(str(uid), "mobile-relay-pairing-code", 5, 3600):
                return JSONResponse(
                    format_mobile_response(None, "尝试过多，请稍后重试", success=False, code=429),
                    status_code=429,
                )
            try:
                desktop = ports.mobile_relay_service().bind_mobile_by_account(
                    user_id=uid,
                    username=username,
                    relay_id=body.relay_id,
                    pairing_code=body.pairing_code,
                )
                if not desktop:
                    return JSONResponse(
                        format_mobile_response(
                            None, "未找到可绑定的电脑执行端", success=False, code=404
                        ),
                        status_code=404,
                    )
                user_public = ports.mobile_user_public_dict(user)
                return format_mobile_response(
                    data={
                        "desktop": desktop,
                        "relay_id": desktop.get("relay_id"),
                        **ports.relay_mobile_auth_payload(user_public, desktop),
                    }
                )
            except RECOVERABLE_ERRORS:
                logger.exception("mobile_relay_bind_account")
                return JSONResponse(
                    format_mobile_response(None, "账号绑定失败", success=False, code=500),
                    status_code=500,
                )

        self.mobile_relay_bind_account = mobile_relay_bind_account

        @router.get("/relay/mobile/desktops", response_model=None)
        async def mobile_relay_desktops(user: MobilePrincipal | None = Depends(get_user)) -> object:
            uid, _ = ports.mobile_user_identity(user)
            if uid <= 0:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )
            try:
                items = ports.mobile_relay_service().list_desktops(user_id=uid)
                return format_mobile_response(data={"items": items, "count": len(items)})
            except RECOVERABLE_ERRORS:
                logger.exception("mobile_relay_desktops")
                return JSONResponse(
                    format_mobile_response(None, "暂时无法获取桌面端", success=False, code=500),
                    status_code=500,
                )

        self.mobile_relay_desktops = mobile_relay_desktops

        @router.post("/relay/tasks", response_model=None)
        async def mobile_relay_create_task(
            body: RelayTaskCreateBody, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            uid, _ = ports.mobile_user_identity(user)
            if uid <= 0:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )
            try:
                payload = dict(body.payload or {})
                payload.setdefault("user_id", uid)
                task = ports.mobile_relay_service().create_task(
                    user_id=uid, relay_id=body.relay_id, kind=body.kind, payload=payload
                )
                if not task:
                    return JSONResponse(
                        format_mobile_response(
                            None, "未找到已绑定的电脑执行端", success=False, code=404
                        ),
                        status_code=404,
                    )
                return format_mobile_response(data={"task": task})
            except RECOVERABLE_ERRORS:
                logger.exception("mobile_relay_create_task")
                return JSONResponse(
                    format_mobile_response(None, "任务创建失败", success=False, code=500),
                    status_code=500,
                )

        self.mobile_relay_create_task = mobile_relay_create_task

        @router.get("/relay/tasks/{task_id}", response_model=None)
        async def mobile_relay_task_status(
            task_id: str, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            uid, _ = ports.mobile_user_identity(user)
            if uid <= 0:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )
            task = ports.mobile_relay_service().get_task(user_id=uid, task_id=task_id)
            if not task:
                return JSONResponse(
                    format_mobile_response(None, "任务不存在", success=False, code=404),
                    status_code=404,
                )
            return format_mobile_response(data={"task": task})

        self.mobile_relay_task_status = mobile_relay_task_status

        @router.post("/relay/tasks/{task_id}/cancel", response_model=None)
        async def mobile_relay_task_cancel(
            task_id: str, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            uid, _ = ports.mobile_user_identity(user)
            if uid <= 0:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )
            task = ports.mobile_relay_service().cancel_task(user_id=uid, task_id=task_id)
            if not task:
                return JSONResponse(
                    format_mobile_response(None, "任务不存在", success=False, code=404),
                    status_code=404,
                )
            return format_mobile_response(data={"task": task})

        self.mobile_relay_task_cancel = mobile_relay_task_cancel

        @router.post("/relay/desktop/poll", response_model=None)
        async def mobile_relay_desktop_poll(body: RelayDesktopPollBody) -> object:
            try:
                data = ports.mobile_relay_service().poll_desktop(
                    relay_id=body.relay_id,
                    desktop_token=body.desktop_token,
                    max_tasks=body.max_tasks,
                )
                if not data:
                    return JSONResponse(
                        format_mobile_response(None, "中继桌面凭证无效", success=False, code=404),
                        status_code=404,
                    )
                return format_mobile_response(data=data)
            except RECOVERABLE_ERRORS:
                logger.exception("mobile_relay_desktop_poll")
                return JSONResponse(
                    format_mobile_response(None, "轮询桌面任务失败", success=False, code=500),
                    status_code=500,
                )

        self.mobile_relay_desktop_poll = mobile_relay_desktop_poll

        @router.post("/relay/desktop/tasks/{task_id}/complete", response_model=None)
        async def mobile_relay_desktop_complete(
            task_id: str, body: RelayDesktopCompleteBody
        ) -> object:
            try:
                task = ports.mobile_relay_service().complete_desktop_task(
                    relay_id=body.relay_id,
                    desktop_token=body.desktop_token,
                    task_id=task_id,
                    status=body.status,
                    result=body.result,
                )
                if not task:
                    return JSONResponse(
                        format_mobile_response(None, "任务或桌面凭证无效", success=False, code=404),
                        status_code=404,
                    )
                return format_mobile_response(data={"task": task})
            except RECOVERABLE_ERRORS:
                logger.exception("mobile_relay_desktop_complete")
                return JSONResponse(
                    format_mobile_response(None, "任务完成回传失败", success=False, code=500),
                    status_code=500,
                )

        self.mobile_relay_desktop_complete = mobile_relay_desktop_complete
