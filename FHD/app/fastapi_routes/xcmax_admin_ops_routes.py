"""XCmax admin remote ops routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse

import app.fastapi_routes.xcmax_admin_patch as _p

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/ops/duty-health", response_model=None)
async def ops_duty_health(request: Request):
    from app.application.ops_closure_status import build_ops_closure_status

    remote = await _p._remote_duty_health(request)
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

@router.post("/ops/dispatch", response_model=None)
async def ops_dispatch(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    payload = dict(body or {})
    payload.setdefault("dispatch_source", "desktop")
    return await _p._market_admin_proxy(
        request,
        "POST",
        "/api/ops/orchestrate/async",
        json_body=payload,
    )

@router.get("/ops/jobs", response_model=None)
async def ops_jobs(request: Request, limit: int = Query(20, ge=1, le=100)):
    return await _p._market_admin_proxy(
        request,
        "GET",
        f"/api/ops/orchestrate/jobs?limit={limit}",
    )

@router.get("/ops/jobs/{job_id}", response_model=None)
async def ops_job_detail(request: Request, job_id: str):
    jid = "".join(ch for ch in str(job_id or "") if ch.isalnum() or ch in "-_")[:128]
    if not jid:
        return JSONResponse({"success": False, "message": "job_id 无效"}, status_code=400)
    return await _p._market_admin_proxy(request, "GET", f"/api/ops/orchestrate/jobs/{jid}")

@router.post("/ops/duty-runs", response_model=None)
async def ops_duty_runs(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    return await _p._market_admin_proxy(
        request,
        "POST",
        "/api/admin/duty-graph/runs",
        json_body=body,
    )

@router.get("/ops/duty-runs/{run_id}", response_model=None)
async def ops_duty_run_detail(request: Request, run_id: int):
    if run_id <= 0:
        return JSONResponse({"success": False, "message": "run_id 无效"}, status_code=400)
    return await _p._market_admin_proxy(request, "GET", f"/api/admin/duty-graph/runs/{run_id}")

@router.get("/ops/closure-status", response_model=None)
async def ops_closure_status(request: Request):
    from app.application.ops_closure_status import build_ops_closure_status

    gate = _p._require_market_admin_session(request)
    if gate is not None:
        return gate
    data = build_ops_closure_status(await _p._remote_duty_health(request))
    return {"success": True, "data": data}

@router.post("/ops/staffing/onboard", response_model=None)
async def ops_staffing_onboard(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
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
    return await _p._market_admin_proxy(
        request,
        "POST",
        "/api/admin/yuangon-onboard/run",
        json_body=payload,
    )

@router.post("/ops/staffing/install-local", response_model=None)
async def ops_staffing_install_local(
    request: Request, body: dict[str, Any] = Body(default_factory=dict)
):
    """从 MODstore Catalog 安装 employee_pack 到本地 mods/_employees/。"""
    gate = _p._require_market_admin_session(request)
    if gate is not None:
        return gate
    pkg_id = str(body.get("employee_id") or body.get("pkg_id") or "").strip()
    if not pkg_id:
        return JSONResponse({"success": False, "message": "employee_id 必填"}, status_code=400)
    try:
        from app.fastapi_routes.mod_store_routes import _install_from_catalog

        result = await _install_from_catalog(pkg_id, "", activate=True)
        if hasattr(result, "model_dump"):
            data = result.model_dump()
        elif isinstance(result, dict):
            data = result
        else:
            data = {"result": str(result)}
        return {"success": bool(data.get("success", True)), "data": data}
    except _p.RECOVERABLE_ERRORS as exc:
        logger.warning("ops_staffing_install_local failed: %s", exc)
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)

@router.post("/ops/staffing/close-gap", response_model=None)
async def ops_staffing_close_gap(
    request: Request, body: dict[str, Any] = Body(default_factory=dict)
):
    """补登记编制缺岗并安装本地缺失 employee_pack（桌面一键闭环）。"""
    from app.application.ops_closure_status import build_ops_closure_status

    gate = _p._require_market_admin_session(request)
    if gate is not None:
        return gate

    before = build_ops_closure_status(await _p._remote_duty_health(request))
    onboard_result: dict[str, Any] | None = None
    missing_remote = list(before.get("missing_remote_employees") or [])
    if missing_remote and not bool(body.get("skip_onboard", False)):
        onboard_result = await _p._market_admin_proxy(
            request,
            "POST",
            "/api/admin/yuangon-onboard/run",
            json_body={"pkg_ids": ",".join(missing_remote)},
        )
        if isinstance(onboard_result, JSONResponse):
            return onboard_result

    mid = build_ops_closure_status(await _p._remote_duty_health(request))
    install_results: list[dict[str, Any]] = []
    if not bool(body.get("skip_install", False)):
        from app.fastapi_routes.mod_store_routes import _install_from_catalog

        for employee_id in list(mid.get("missing_local_employee_packs") or []):
            try:
                result = await _install_from_catalog(employee_id, "", activate=True)
                if hasattr(result, "model_dump"):
                    data = result.model_dump()
                elif isinstance(result, dict):
                    data = result
                else:
                    data = {"result": str(result)}
                install_results.append(
                    {
                        "employee_id": employee_id,
                        "success": bool(data.get("success", True)),
                        "message": str(data.get("message") or ""),
                    }
                )
            except _p.RECOVERABLE_ERRORS as exc:
                install_results.append(
                    {"employee_id": employee_id, "success": False, "message": str(exc)}
                )

    after = build_ops_closure_status(await _p._remote_duty_health(request))
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
