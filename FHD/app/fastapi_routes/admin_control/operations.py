"""Operations control-plane operations with explicit callback dependencies."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, cast

from fastapi import Body, Query, Request
from fastapi.responses import JSONResponse

from .common import installation_payload
from .ports import AdminGate, ErrorPolicy, JsonObject, MarketProxy


class Operations:
    def __init__(
        self,
        *,
        errors: ErrorPolicy,
        proxy: MarketProxy,
        duty_health: Callable[[Request], Awaitable[JsonObject]],
        gate: AdminGate,
    ) -> None:
        self._errors = errors
        self._proxy = proxy
        self._duty_health = duty_health
        self._gate = gate

    async def _remote_duty_health(self, request: Request) -> dict[str, Any]:
        health_payload = await self._proxy(request, "GET", "/api/admin/duty-graph/health")
        if isinstance(health_payload, dict):
            return health_payload
        if hasattr(health_payload, "body"):
            try:
                return cast(
                    "dict[str, Any]",
                    json.loads(getattr(health_payload, "body", b"") or b"{}"),
                )
            except self._errors.recoverable():
                return {}
        return {}

    async def ops_duty_health(self, request: Request):
        from app.application.ops_closure_status import build_ops_closure_status

        remote = await self._duty_health(request)
        closure = build_ops_closure_status(remote if isinstance(remote, dict) else {})
        if not isinstance(remote, dict):
            return closure.get("remote_health") or {
                "success": False,
                "staffing": closure.get("staffing") or {},
            }
        merged = {**remote, "staffing": closure.get("staffing") or remote.get("staffing") or {}}
        merged["planned_employee_ids"] = closure.get("planned_employee_ids")
        merged["registered_employee_ids"] = closure.get("registered_employee_ids")
        merged["planned_local_installed_count"] = closure.get("planned_local_installed_count")
        merged["extra_local_employee_pack_ids"] = closure.get("extra_local_employee_pack_ids")
        return merged

    async def ops_dispatch(
        self,
        request: Request,
        body: dict[str, Any] = Body(default_factory=dict),
    ):
        payload = dict(body or {})
        payload.setdefault("dispatch_source", "desktop")
        return await self._proxy(request, "POST", "/api/ops/orchestrate/async", json_body=payload)

    async def ops_jobs(self, request: Request, limit: int = Query(20, ge=1, le=100)):
        return await self._proxy(request, "GET", f"/api/ops/orchestrate/jobs?limit={limit}")

    async def ops_job_detail(self, request: Request, job_id: str):
        jid = "".join(ch for ch in str(job_id or "") if ch.isalnum() or ch in "-_")[:128]
        if not jid:
            return JSONResponse({"success": False, "message": "job_id 无效"}, status_code=400)
        return await self._proxy(request, "GET", f"/api/ops/orchestrate/jobs/{jid}")

    async def ops_duty_runs(
        self,
        request: Request,
        body: dict[str, Any] = Body(default_factory=dict),
    ):
        return await self._proxy(request, "POST", "/api/admin/duty-graph/runs", json_body=body)

    async def ops_duty_run_detail(self, request: Request, run_id: int):
        if run_id <= 0:
            return JSONResponse({"success": False, "message": "run_id 无效"}, status_code=400)
        return await self._proxy(request, "GET", f"/api/admin/duty-graph/runs/{run_id}")

    async def ops_closure_status(self, request: Request):
        from app.application.ops_closure_status import build_ops_closure_status

        gate = self._gate(request)
        if gate is not None:
            return gate
        data = build_ops_closure_status(await self._duty_health(request))
        return {"success": True, "data": data}

    async def ops_runtime_inventory(self, request: Request):
        """Desired×actual 运行时真相清单（拓扑 SSOT + 本机探针），并刷新公开投影。"""
        gate = self._gate(request)
        if gate is not None:
            return gate
        from app.application.runtime_inventory import write_runtime_inventory_projection

        try:
            result = write_runtime_inventory_projection(host="127.0.0.1")
        except self._errors.recoverable() as exc:
            self._errors.logger.warning("runtime inventory probe failed: %s", exc)
            return {"success": False, "error": str(exc)}
        snapshot = result.get("snapshot") or {}
        return {"success": True, "data": snapshot, "publication": result.get("publication") or {}}

    async def ops_staffing_onboard(
        self,
        request: Request,
        body: dict[str, Any] = Body(default_factory=dict),
    ):
        """将编制缺岗员工登记到 MODstore Catalog（代理 yuangon-onboard/run）。"""
        payload: dict[str, Any] = {
            "dry_run": bool(body.get("dry_run", False)),
            "force": bool(body.get("force", False)),
        }
        pkg_ids = body.get("employee_ids") or body.get("pkg_ids")
        if isinstance(pkg_ids, list):
            payload["pkg_ids"] = ",".join(str(x).strip() for x in pkg_ids if str(x).strip())
        elif isinstance(pkg_ids, str) and pkg_ids.strip():
            payload["pkg_ids"] = pkg_ids.strip()
        return await self._proxy(
            request, "POST", "/api/admin/yuangon-onboard/run", json_body=payload
        )

    async def ops_staffing_install_local(
        self,
        request: Request,
        body: dict[str, Any] = Body(default_factory=dict),
    ):
        """从 MODstore Catalog 安装 employee_pack 到本地 mods/_employees/。"""
        gate = self._gate(request)
        if gate is not None:
            return gate
        pkg_id = str(body.get("employee_id") or body.get("pkg_id") or "").strip()
        if not pkg_id:
            return JSONResponse({"success": False, "message": "employee_id 必填"}, status_code=400)
        try:
            from app.fastapi_routes.mod_store_routes import _install_from_catalog

            result = await _install_from_catalog(pkg_id, "", activate=True)
            data = installation_payload(result)
            return {"success": bool(data.get("success", True)), "data": data}
        except self._errors.recoverable() as exc:
            self._errors.logger.warning("ops_staffing_install_local failed: %s", exc)
            return JSONResponse({"success": False, "message": str(exc)}, status_code=500)

    async def ops_staffing_close_gap(
        self,
        request: Request,
        body: dict[str, Any] = Body(default_factory=dict),
    ):
        """补登记编制缺岗并安装本地缺失 employee_pack（桌面一键闭环）。"""
        from app.application.ops_closure_status import build_ops_closure_status

        gate = self._gate(request)
        if gate is not None:
            return gate
        before = build_ops_closure_status(await self._duty_health(request))
        onboard_result: dict[str, Any] | JSONResponse | None = None
        missing_remote = list(before.get("missing_remote_employees") or [])
        if missing_remote and (not bool(body.get("skip_onboard", False))):
            onboard_result = await self._proxy(
                request,
                "POST",
                "/api/admin/yuangon-onboard/run",
                json_body={"pkg_ids": ",".join(missing_remote)},
            )
            if isinstance(onboard_result, JSONResponse):
                return onboard_result
        mid = build_ops_closure_status(await self._duty_health(request))
        install_results: list[dict[str, Any]] = []
        if not bool(body.get("skip_install", False)):
            from app.fastapi_routes.mod_store_routes import _install_from_catalog

            for employee_id in list(mid.get("missing_local_employee_packs") or []):
                try:
                    result = await _install_from_catalog(employee_id, "", activate=True)
                    data = installation_payload(result)
                    install_results.append(
                        {
                            "employee_id": employee_id,
                            "success": bool(data.get("success", True)),
                            "message": str(data.get("message") or ""),
                        }
                    )
                except self._errors.recoverable() as exc:
                    install_results.append(
                        {"employee_id": employee_id, "success": False, "message": str(exc)}
                    )
        after = build_ops_closure_status(await self._duty_health(request))
        onboard_ok = True
        if isinstance(onboard_result, dict):
            onboard_ok = bool(onboard_result.get("success", True))
        return {
            "success": True,
            "data": {
                "before": before,
                "after": after,
                "onboard": onboard_result,
                "onboard_ok": onboard_ok,
                "install_results": install_results,
            },
        }
