"""DeviceRoutes: explicit collaborators for one mobile capability."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import Table

from app.application.mobile_extensions.protocols import (
    DatabaseCall,
    EnsureMobileDeviceTableCall,
    EnsureOutboxTableCall,
    MobilePrincipal,
    NowCall,
    UserDependency,
)
from app.fastapi_routes.mobile_extensions.models import (
    DeviceRegisterBody,
)
from app.utils.device_system.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS


class DeviceTokenRecord(Protocol):
    """Writable instance values of the legacy Column-declared device model."""

    device_label: str
    platform: str
    fcm_token: str
    push_provider: str
    push_token: str
    product_sku: str
    updated_at: datetime


@dataclass(frozen=True)
class DeviceRoutesPorts:
    database: DatabaseCall
    warning: Callable[[str, Exception], None]
    ensure_mobile_device_table: EnsureMobileDeviceTableCall
    now: NowCall
    ensure_outbox_table: EnsureOutboxTableCall


class DeviceRoutes:
    def __init__(self, ports: DeviceRoutesPorts, get_user: UserDependency) -> None:
        self.ports = ports
        self.router = router = APIRouter()

        def _ensure_mobile_device_table() -> None:
            try:
                from sqlalchemy import inspect

                from app.db.models.mobile_device import MobileDeviceToken

                with ports.database() as db:
                    bind = db.get_bind()
                    insp = inspect(bind)
                    if not insp.has_table(MobileDeviceToken.__tablename__):
                        cast("Table", MobileDeviceToken.__table__).create(bind, checkfirst=True)
            except RECOVERABLE_ERRORS as exc:
                ports.warning("mobile_device_tokens ensure: %s", exc)

        self._ensure_mobile_device_table = _ensure_mobile_device_table

        def _ensure_outbox_table() -> None:
            try:
                from sqlalchemy import inspect

                from app.db.models.mobile_notification import MobileNotificationOutbox

                with ports.database() as db:
                    bind = db.get_bind()
                    insp = inspect(bind)
                    if not insp.has_table(MobileNotificationOutbox.__tablename__):
                        cast("Table", MobileNotificationOutbox.__table__).create(
                            bind, checkfirst=True
                        )
            except RECOVERABLE_ERRORS as exc:
                ports.warning("mobile_notification_outbox ensure: %s", exc)

        self._ensure_outbox_table = _ensure_outbox_table

        @router.post("/devices/register", response_model=None)
        async def mobile_device_register(
            body: DeviceRegisterBody, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )
            ports.ensure_mobile_device_table()
            from app.db.models.mobile_device import MobileDeviceToken

            token = (body.push_token or body.fcm_token).strip()
            provider = (body.push_provider or "fcm").strip().lower()[:16]
            if not token:
                return JSONResponse(
                    format_mobile_response(None, "缺少 push_token", success=False, code=400),
                    status_code=400,
                )
            with ports.database() as db:
                row = (
                    db.query(MobileDeviceToken)
                    .filter(
                        MobileDeviceToken.user_id == user.id,
                        MobileDeviceToken.fcm_token == body.fcm_token.strip(),
                    )
                    .first()
                )
                if row:
                    record = cast("DeviceTokenRecord", row)
                    record.device_label = body.device_label[:200]
                    record.platform = body.platform[:32]
                    record.fcm_token = body.fcm_token.strip()[:512]
                    record.push_provider = provider
                    record.push_token = token
                    record.product_sku = (body.product_sku or "personal")[:32]
                    record.updated_at = ports.now()
                else:
                    db.add(
                        MobileDeviceToken(
                            user_id=user.id,
                            fcm_token=body.fcm_token.strip(),
                            push_provider=provider,
                            push_token=token,
                            product_sku=(body.product_sku or "personal")[:32],
                            platform=body.platform[:32],
                            device_label=body.device_label[:200],
                        )
                    )
            return format_mobile_response(data={"registered": True})

        self.mobile_device_register = mobile_device_register

        @router.delete("/devices/unregister", response_model=None)
        async def mobile_device_unregister(
            fcm_token: str = Query(..., min_length=8),
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )
            ports.ensure_mobile_device_table()
            from app.db.models.mobile_device import MobileDeviceToken

            with ports.database() as db:
                db.query(MobileDeviceToken).filter(
                    MobileDeviceToken.user_id == user.id,
                    MobileDeviceToken.fcm_token == fcm_token.strip(),
                ).delete()
            return format_mobile_response(data={"unregistered": True})

        self.mobile_device_unregister = mobile_device_unregister

        @router.get("/notifications/pending", response_model=None)
        async def mobile_notifications_pending(
            limit: int = Query(50, ge=1, le=200), user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """自建推送后台通道:返回未送达的离线通知并标记 delivered（客户端 WorkManager 轮询）。"""
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )
            ports.ensure_outbox_table()
            import json as _json

            from app.db.models.mobile_notification import MobileNotificationOutbox

            items: list[dict] = []
            with ports.database() as db:
                rows = (
                    db.query(MobileNotificationOutbox)
                    .filter(
                        MobileNotificationOutbox.user_id == user.id,
                        MobileNotificationOutbox.delivered.is_(False),
                    )
                    .order_by(MobileNotificationOutbox.created_at.asc())
                    .limit(limit)
                    .all()
                )
                now = ports.now()
                for r in rows:
                    try:
                        data = _json.loads(r.data_json or "{}")
                    except (ValueError, TypeError):
                        data = {}
                    items.append(
                        {
                            "id": r.id,
                            "title": r.title,
                            "body": r.body,
                            "route": r.route,
                            "channel": r.channel,
                            "data": data,
                        }
                    )
                    r.delivered = True
                    r.delivered_at = now
            return format_mobile_response(data={"notifications": items})

        self.mobile_notifications_pending = mobile_notifications_pending
