"""DesktopDeviceRoutes: 桌面设备心跳与在线状态（供移动端任务页展示执行端）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from app.application.mobile_extensions.protocols import MobilePrincipal, UserDependency
from app.utils.device_system.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS

ONLINE_WINDOW_SECONDS = 120


class DesktopHeartbeatCall(Protocol):
    def __call__(
        self,
        *,
        user_id: int,
        tenant_id: str,
        device_id: str,
        label: str,
        platform: str,
        app_version: str,
        capabilities: dict[str, Any],
    ) -> dict[str, Any]: ...


class DesktopDeviceListCall(Protocol):
    def __call__(
        self, *, user_id: int, tenant_id: str, online_within_seconds: int
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class DesktopDeviceRoutesPorts:
    upsert_heartbeat: DesktopHeartbeatCall
    list_devices: DesktopDeviceListCall


def _device_payload(device: dict[str, Any]) -> dict[str, Any]:
    last_seen = device.get("last_seen_at")
    if isinstance(last_seen, datetime):
        last_seen_text = last_seen.isoformat(timespec="seconds")
    else:
        last_seen_text = str(last_seen or "")
    return {
        "device_id": str(device.get("device_id") or ""),
        "label": str(device.get("label") or ""),
        "platform": str(device.get("platform") or "desktop"),
        "app_version": str(device.get("app_version") or ""),
        "online": bool(device.get("online")),
        "last_seen_at": last_seen_text,
        "capabilities": device.get("capabilities") or {},
    }


class DesktopDeviceRoutes:
    def __init__(self, ports: DesktopDeviceRoutesPorts, get_user: UserDependency) -> None:
        self.ports = ports
        self.router = router = APIRouter()

        def _unauthorized() -> JSONResponse:
            return JSONResponse(
                format_mobile_response(None, "未授权", success=False, code=401),
                status_code=401,
            )

        def _scope(user: MobilePrincipal) -> tuple[int, str]:
            return int(user.id), str(getattr(user, "tenant_id", "") or "")

        @router.post("/devices/desktop/heartbeat", response_model=None)
        async def desktop_device_heartbeat(
            body: dict[str, Any] = Body(default_factory=dict),
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            if user is None:
                return _unauthorized()
            device_id = str((body or {}).get("device_id") or "").strip()
            if not device_id:
                return JSONResponse(
                    format_mobile_response(
                        None, "缺少设备标识", success=False, code=400
                    ),
                    status_code=400,
                )
            user_id, tenant_id = _scope(user)
            capabilities = (body or {}).get("capabilities")
            try:
                device = ports.upsert_heartbeat(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    device_id=device_id,
                    label=str((body or {}).get("label") or "").strip(),
                    platform=str((body or {}).get("platform") or "desktop").strip()
                    or "desktop",
                    app_version=str((body or {}).get("app_version") or "").strip(),
                    capabilities=capabilities
                    if isinstance(capabilities, dict)
                    else {},
                )
            except RECOVERABLE_ERRORS:
                return JSONResponse(
                    format_mobile_response(
                        None, "设备状态上报失败，请稍后重试", success=False, code=500
                    ),
                    status_code=500,
                )
            return format_mobile_response(_device_payload(device))

        @router.get("/devices/desktop", response_model=None)
        async def desktop_device_list(
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            if user is None:
                return _unauthorized()
            user_id, tenant_id = _scope(user)
            try:
                devices = ports.list_devices(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    online_within_seconds=ONLINE_WINDOW_SECONDS,
                )
            except RECOVERABLE_ERRORS:
                return JSONResponse(
                    format_mobile_response(
                        None, "设备列表加载失败，请稍后重试", success=False, code=500
                    ),
                    status_code=500,
                )
            items = [_device_payload(device) for device in devices]
            return format_mobile_response(
                {
                    "items": items,
                    "count": len(items),
                    "online_count": sum(1 for item in items if item["online"]),
                }
            )

        self.desktop_device_heartbeat = desktop_device_heartbeat
        self.desktop_device_list = desktop_device_list


__all__ = [
    "DesktopDeviceRoutes",
    "DesktopDeviceRoutesPorts",
    "ONLINE_WINDOW_SECONDS",
]
