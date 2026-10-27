"""Admin-session market transport and dispatch, with explicit caller authorization."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from app.application.admin_control.protocols import (
    AdminGate,
    ErrorPolicy,
    LocalProxy,
    MarketProxy,
    MarketTransport,
)

from .common import read_json_object


class MarketGateway:
    def __init__(
        self,
        *,
        errors: ErrorPolicy,
        gate: AdminGate,
        proxy: MarketProxy,
        maintenance: LocalProxy,
        transport: Callable[[], MarketTransport],
    ) -> None:
        self._errors = errors
        self._transport = transport
        self._gate = gate
        self._proxy = proxy
        self._maintenance = maintenance

    async def _market_admin_proxy(
        self,
        request: Request,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        require_admin_session: bool = True,
        authorization_override: str = "",
    ):
        """Proxy server-function calls through the market token bound to the local session."""
        if require_admin_session:
            gate = self._gate(request)
            if gate is not None:
                return gate
        if path in {"/api/admin/yuangon-onboard/status", "/api/admin/yuangon-onboard/run"}:
            from app.application.modstore_local_client import prefer_local_modstore

            if prefer_local_modstore():
                from app.application import self_maintenance_app_service as sm_svc

                try:
                    if method.upper() == "GET":
                        return await sm_svc.get_yuangon_onboard_status_local()
                    if method.upper() == "POST":
                        return await sm_svc.run_yuangon_onboard_local(json_body or {})
                except self._errors.recoverable() as exc:
                    self._errors.logger.warning(
                        "local yuangon onboarding failed path=%s: %s", path, exc
                    )
                    return JSONResponse(
                        {"success": False, "message": f"本地元工登记服务不可用: {exc}"},
                        status_code=502,
                    )
        try:
            transport = self._transport()
        except self._errors.recoverable() as exc:
            return JSONResponse(
                {"success": False, "message": f"市场账号代理不可用: {exc}"}, status_code=500
            )
        body_for_auth = json_body if isinstance(json_body, dict) else {}
        authorization = transport.authorization_header(authorization_override)
        if not authorization:
            authorization = await transport.resolve_authorization(request, body_for_auth)
        if not authorization:
            return JSONResponse(
                {
                    "success": False,
                    "message": "尚未绑定修茈服务器账号；请重新登录或在设置中同步市场 Authorization",
                },
                status_code=401,
            )
        payload = await transport.request(
            method,
            path,
            json_body=json_body,
            authorization=authorization,
            return_error_payload=True,
        )
        if isinstance(payload, JSONResponse):
            return payload
        if isinstance(payload, dict) and payload.get("__proxy_error__"):
            status_code = int(payload.get("status_code") or 502)
            raw_error = payload.get("payload")
            return JSONResponse(
                {
                    "success": False,
                    "message": transport.error_message(raw_error, status_code),
                    "data": raw_error,
                },
                status_code=status_code,
            )
        return payload

    async def _xcmax_market_proxy_impl(self, request: Request, subpath: str):
        """编制图 LLM / 员工执行等：经会话市场 token 转发至 MODstore ``/api/...``。"""
        method = request.method.upper()
        json_body: dict[str, Any] | None = None
        if method in {"POST", "PUT", "PATCH"}:
            json_body = await read_json_object(request, self._errors)
        api_path = f"/api/{str(subpath or '').lstrip('/')}"
        if api_path.startswith("/api/ops/self-maintenance/"):
            return await self._maintenance(request, method, api_path, json_body=json_body)
        return await self._proxy(request, method, api_path, json_body=json_body)
