"""One authenticated target for loop reads and commands; never replay on another host."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import parse_qs, urlsplit

from fastapi import Body, Query, Request
from fastapi.responses import JSONResponse

from app.application.admin_control.protocols import AdminGate, ErrorPolicy, MarketProxy


class SelfMaintenance:
    def __init__(self, *, errors: ErrorPolicy, proxy: MarketProxy, gate: AdminGate) -> None:
        self._errors, self._proxy, self._gate = errors, proxy, gate

    async def _self_maintenance_local_or_proxy(
        self,
        request: Request,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ):
        if not path.startswith("/api/ops/self-maintenance/"):
            return None
        denied = self._gate(request)
        if denied is not None:
            return denied
        # Cloud is the default. Local runs require an explicit existing deployment flag.
        local = os.environ.get("MODSTORE_LOCAL_AUTOMATION", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        try:
            if not local:
                payload = await self._proxy(request, method, path, json_body=json_body)
            else:
                from app.application import self_maintenance_app_service as svc
                from app.fastapi_routes.market_account import _authorization_from_request

                auth = _authorization_from_request(request, json_body or {})
                parsed = urlsplit(path)
                body = json_body or {}
                if parsed.path.endswith("/status") and method.upper() == "GET":
                    limit = int(parse_qs(parsed.query).get("limit", [80])[0])
                    payload = await svc.get_runtime_status_local(limit=limit, authorization=auth)
                elif parsed.path.endswith("/governance-review") and method.upper() == "POST":
                    payload = await svc.governance_review_local(
                        note=str(body.get("note") or ""), authorization=auth
                    )
                elif parsed.path.endswith("/run") and method.upper() == "POST":
                    payload = await svc.force_run_local(
                        reason=str(body.get("reason") or "admin_force_run"), authorization=auth
                    )
                else:
                    return JSONResponse({"message": "不支持的维护操作"}, status_code=404)
            if isinstance(payload, dict) and method.upper() == "GET":
                from app.application.modstore_local_client import modstore_base_url
                from app.fastapi_routes.market_bridge.settings import _market_api_base_url

                host = urlsplit(modstore_base_url() if local else _market_api_base_url()).hostname
                return {
                    **payload,
                    "control_plane": {"target": "local" if local else "market", "host": host},
                }
            return payload
        except self._errors.recoverable() as exc:
            self._errors.logger.warning(
                "self-maintenance target unavailable: %s", type(exc).__name__
            )
            return JSONResponse(
                {
                    "ok": False,
                    "message": "维护监控服务连接失败，请检查已配置的运营服务；任务未自动重发。",
                },
                status_code=502,
            )

    async def local_self_maintenance_status(
        self,
        request: Request,
        limit: int = Query(default=80, ge=1, le=300),
    ):
        """Compatibility URL; shares the configured control plane with all loop actions."""
        return await self._self_maintenance_local_or_proxy(
            request,
            "GET",
            f"/api/ops/self-maintenance/status?limit={limit}",
        )

    async def local_self_maintenance_governance_review(
        self,
        request: Request,
        body: dict[str, Any] = Body(default_factory=dict),
    ):
        return await self._self_maintenance_local_or_proxy(
            request,
            "POST",
            "/api/ops/self-maintenance/governance-review",
            json_body=body,
        )
