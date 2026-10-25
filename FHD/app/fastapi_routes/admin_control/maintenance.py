"""SelfMaintenance control-plane operations with explicit callback dependencies."""

from __future__ import annotations

from typing import Any

from fastapi import Body, Query, Request
from fastapi.responses import JSONResponse

from .port_contracts import ErrorPolicy, MarketProxy


class SelfMaintenance:
    def __init__(self, *, errors: ErrorPolicy, proxy: MarketProxy) -> None:
        self._errors = errors
        self._proxy = proxy

    async def _self_maintenance_local_or_proxy(
        self,
        request: Request,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ):
        """自维护 loop runtime：优先本地 MODstore :8788，远端 market-proxy 404 时再试本地。"""
        if not path.startswith("/api/ops/self-maintenance/"):
            return None
        from app.application import self_maintenance_app_service as sm_svc
        from app.application.modstore_local_client import prefer_local_modstore
        from app.fastapi_routes.market_account import _authorization_from_request

        authorization = _authorization_from_request(request, json_body or {})

        async def _call_local() -> dict[str, Any] | None:
            if path.startswith("/api/ops/self-maintenance/status"):
                limit = 80
                if "?" in path:
                    for part in path.split("?", 1)[1].split("&"):
                        if part.startswith("limit="):
                            try:
                                limit = int(part.split("=", 1)[1])
                            except ValueError:
                                pass
                return await sm_svc.get_runtime_status_local(
                    limit=limit, authorization=authorization
                )
            if path == "/api/ops/self-maintenance/governance-review" and method.upper() == "POST":
                note = str((json_body or {}).get("note") or "")
                return await sm_svc.governance_review_local(note=note, authorization=authorization)
            if path == "/api/ops/self-maintenance/run" and method.upper() == "POST":
                reason = str((json_body or {}).get("reason") or "admin_force_run")
                return await sm_svc.force_run_local(reason=reason, authorization=authorization)
            return None

        if prefer_local_modstore():
            try:
                local_payload = await _call_local()
                if local_payload is not None:
                    return local_payload
            except self._errors.recoverable() as exc:
                self._errors.logger.warning("local self-maintenance failed path=%s: %s", path, exc)
        proxied = await self._proxy(request, method, path, json_body=json_body)
        if isinstance(proxied, JSONResponse) and proxied.status_code == 404:
            try:
                local_payload = await _call_local()
                if local_payload is not None:
                    return local_payload
            except self._errors.recoverable() as exc:
                self._errors.logger.warning(
                    "self-maintenance local fallback after upstream 404 path=%s: %s", path, exc
                )
        return proxied

    async def local_self_maintenance_status(
        self, request: Request, limit: int = Query(default=80, ge=1, le=300)
    ):
        """本机自维护 loop runtime 状态（直连 MODstore :8788）。"""
        from app.application import self_maintenance_app_service as sm_svc
        from app.fastapi_routes.domains.misc.helpers import _session_id_from_request
        from app.fastapi_routes.market_account import _authorization_from_request

        if not _session_id_from_request(request):
            return JSONResponse({"success": False, "message": "请先登录"}, status_code=401)
        authorization = _authorization_from_request(request, {})
        try:
            return await sm_svc.get_runtime_status_local(limit=limit, authorization=authorization)
        except self._errors.recoverable() as exc:
            return JSONResponse({"success": False, "message": str(exc)}, status_code=502)

    async def local_self_maintenance_governance_review(
        self,
        request: Request,
        body: dict[str, Any] = Body(default_factory=dict),
    ):
        """本机自维护 loop 治理审计复核。"""
        from app.application import self_maintenance_app_service as sm_svc
        from app.fastapi_routes.domains.misc.helpers import _session_id_from_request
        from app.fastapi_routes.market_account import _authorization_from_request

        if not _session_id_from_request(request):
            return JSONResponse({"success": False, "message": "请先登录"}, status_code=401)
        authorization = _authorization_from_request(request, body if isinstance(body, dict) else {})
        try:
            return await sm_svc.governance_review_local(
                note=str(body.get("note") or ""), authorization=authorization
            )
        except self._errors.recoverable() as exc:
            return JSONResponse({"success": False, "message": str(exc)}, status_code=502)
