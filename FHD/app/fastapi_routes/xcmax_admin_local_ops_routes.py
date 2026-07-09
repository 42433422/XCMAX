"""XCmax admin local ops routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse

import app.fastapi_routes.xcmax_admin_patch as _p

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/local/duty-graph/health", response_model=None)
async def local_duty_graph_health(request: Request):
    """本机编制图 health（不代理远端 MODstore）。"""
    from app.application.local_duty_graph_health import build_local_duty_graph_health
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

    if not _session_id_from_request(request):
        return JSONResponse(
            {"success": False, "message": "请先登录"},
            status_code=401,
        )
    return build_local_duty_graph_health()

@router.get("/local/ops/self-maintenance/status", response_model=None)
async def local_self_maintenance_status(
    request: Request,
    limit: int = Query(default=80, ge=1, le=300),
):
    """本机自维护 loop runtime 状态（直连 MODstore :8788）。"""
    from app.application import self_maintenance_app_service as sm_svc
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request
    from app.fastapi_routes.market_account import _authorization_from_request

    if not _session_id_from_request(request):
        return JSONResponse(
            {"success": False, "message": "请先登录"},
            status_code=401,
        )
    authorization = _authorization_from_request(request, {})
    try:
        return await sm_svc.get_runtime_status_local(
            limit=limit,
            authorization=authorization,
        )
    except _p.RECOVERABLE_ERRORS as exc:
        return JSONResponse(
            {"success": False, "message": str(exc)},
            status_code=502,
        )

@router.post("/local/ops/self-maintenance/governance-review", response_model=None)
async def local_self_maintenance_governance_review(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
):
    """本机自维护 loop 治理审计复核。"""
    from app.application import self_maintenance_app_service as sm_svc
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request
    from app.fastapi_routes.market_account import _authorization_from_request

    if not _session_id_from_request(request):
        return JSONResponse(
            {"success": False, "message": "请先登录"},
            status_code=401,
        )
    authorization = _authorization_from_request(request, body if isinstance(body, dict) else {})
    try:
        return await sm_svc.governance_review_local(
            note=str(body.get("note") or ""),
            authorization=authorization,
        )
    except _p.RECOVERABLE_ERRORS as exc:
        return JSONResponse(
            {"success": False, "message": str(exc)},
            status_code=502,
        )

@router.get("/local/employee-cron/jobs", response_model=None)
async def local_employee_cron_jobs(request: Request):
    """本机员工定时任务列表（管理端点火状态）。"""
    from app.application.employee_runtime.scheduler import get_employee_cron_jobs
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

    if not _session_id_from_request(request):
        return JSONResponse(
            {"success": False, "message": "请先登录"},
            status_code=401,
        )
    return {"success": True, "source": "local", "jobs": get_employee_cron_jobs()}

@router.post("/local/employee-cron/jobs/{job_id}/run", response_model=None)
async def local_employee_cron_job_run(
    request: Request,
    job_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
):
    """手动触发本机员工定时任务，供管理端立即验证 daily 员工是否能跑。"""
    from app.application.employee_runtime.scheduler import run_employee_cron_job
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

    sid = _session_id_from_request(request)
    if not sid:
        return JSONResponse(
            {"success": False, "message": "请先登录"},
            status_code=401,
        )
    payload = body.get("input_data") if isinstance(body.get("input_data"), dict) else {}
    task = str(body.get("task") or "").strip() or None
    try:
        user_id = int(body.get("user_id") or 0)
    except (TypeError, ValueError):
        user_id = 0
    result = run_employee_cron_job(
        job_id,
        task=task,
        input_data=payload,
        user_id=user_id,
        workspace_root=str(body.get("workspace_root") or "").strip() or None,
        session_id=str(body.get("session_id") or sid),
        source="manual",
    )
    if not result.get("success") and "unknown employee cron job" in str(result.get("error") or ""):
        return JSONResponse(result, status_code=404)
    return result

@router.get("/local/employees/{employee_id}/status", response_model=None)
async def local_employee_status(request: Request, employee_id: str):
    """本机员工包部署态与执行统计（编制图 Phase2，不代理 MODstore）。"""
    from app.application.local_duty_graph_health import build_local_employee_status
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

    if not _session_id_from_request(request):
        return JSONResponse(
            {"success": False, "message": "请先登录"},
            status_code=401,
        )
    pid = str(employee_id or "").strip()
    if not pid:
        return JSONResponse({"success": False, "message": "employee_id 必填"}, status_code=400)
    return build_local_employee_status(pid)

@router.post("/local/employees/{employee_id}/execute", response_model=None)
async def local_employee_execute(
    request: Request,
    employee_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
):
    """管理端本机员工执行入口：绕开远端代理，直接调用 FHD employee_runtime。"""
    from app.application.auth_permission_resolver import require_allowed
    from app.application.employee_runtime.executor import execute_employee_task_local
    from app.application.employee_runtime.result_verifier import verify_employee_run_result
    from app.application.employee_runtime.run_ledger import (
        create_employee_run_log,
        finish_employee_run_log,
    )
    from app.application.session_account_meta import enrich_session_meta_with_tenant
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request
    from app.infrastructure.auth.dependencies import resolve_session_user

    sid = _session_id_from_request(request)
    if not sid:
        return JSONResponse(
            {"success": False, "message": "请先登录"},
            status_code=401,
        )
    user = resolve_session_user(request)
    if user is None:
        return JSONResponse({"success": False, "message": "请先登录"}, status_code=401)
    meta = enrich_session_meta_with_tenant(sid, user)
    require_allowed(
        user=user,
        account_kind=str(meta.get("account_kind") or "admin"),
        session_meta=meta,
        route=f"/local/employees/{employee_id}/execute",
    )
    pid = str(employee_id or "").strip()
    if not pid:
        return JSONResponse({"success": False, "message": "employee_id 必填"}, status_code=400)
    task = str(body.get("task") or "").strip()
    if not task:
        return JSONResponse({"success": False, "message": "task 必填"}, status_code=400)
    raw_input = body.get("input_data")
    if raw_input is not None and not isinstance(raw_input, dict):
        return JSONResponse({"success": False, "message": "input_data 必须是对象"}, status_code=400)
    payload = dict(raw_input or {})
    for key in ("approved_write", "allow_write", "write_token", "approval_token"):
        if key in body and key not in payload:
            payload[key] = body[key]
    payload.setdefault("trigger", "admin_execute")
    try:
        user_id = int(body.get("user_id") or getattr(user, "id", 0) or 0)
    except (TypeError, ValueError):
        user_id = 0
    retry_max = max(1, min(int(body.get("retry_max") or 3), 5))
    tenant_id = meta.get("tenant_id")
    run_id = create_employee_run_log(
        employee_id=pid,
        input_payload={"task": task, **payload},
        tenant_id=int(tenant_id) if tenant_id else None,
        session_id=sid,
        user_id=user_id or None,
    )
    result: dict[str, Any] = {"success": False, "message": "未执行"}
    last_error = ""
    for attempt in range(1, retry_max + 1):
        result = execute_employee_task_local(
            pid,
            task,
            payload,
            user_id=user_id,
            workspace_root=str(body.get("workspace_root") or "").strip() or None,
            session_id=str(body.get("session_id") or sid),
        )
        ok, reason = verify_employee_run_result(pid, result if isinstance(result, dict) else {})
        if ok and result.get("success") is not False:
            finish_employee_run_log(
                run_id,
                status="success",
                output=result if isinstance(result, dict) else {},
                attempts=attempt,
                verified=True,
            )
            return {
                "success": True,
                "source": "local",
                "run_id": run_id,
                "attempts": attempt,
                "data": result,
            }
        last_error = reason or str(result.get("message") or result.get("error") or "执行失败")
    finish_employee_run_log(
        run_id,
        status="failed",
        output=result if isinstance(result, dict) else {},
        error=last_error,
        attempts=retry_max,
        verified=False,
    )
    return {
        "success": False,
        "source": "local",
        "run_id": run_id,
        "attempts": retry_max,
        "message": last_error,
        "data": result,
    }

@router.get("/local/employees/{employee_id}/runs", response_model=None)
async def local_employee_runs(request: Request, employee_id: str, limit: int = 50):
    from app.application.employee_runtime.run_ledger import list_employee_run_logs
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

    if not _session_id_from_request(request):
        return JSONResponse({"success": False, "message": "请先登录"}, status_code=401)
    pid = str(employee_id or "").strip()
    if not pid:
        return JSONResponse({"success": False, "message": "employee_id 必填"}, status_code=400)
    return {"success": True, "data": list_employee_run_logs(pid, limit=limit)}

@router.get("/local/employees/{employee_id}/manifest", response_model=None)
async def local_employee_manifest(request: Request, employee_id: str):
    """读本机 mods/_employees/<id>/manifest.json（编制图 LLM/依赖解析）。"""
    from app.application.local_duty_graph_health import read_local_employee_manifest
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

    if not _session_id_from_request(request):
        return JSONResponse(
            {"success": False, "message": "请先登录"},
            status_code=401,
        )
    pid = str(employee_id or "").strip()
    if not pid:
        return JSONResponse({"success": False, "message": "employee_id 必填"}, status_code=400)
    row = read_local_employee_manifest(pid)
    if not row:
        return JSONResponse(
            {"success": False, "message": f"员工包不存在: {pid}"},
            status_code=404,
        )
    return row
