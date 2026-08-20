# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.xcmax_admin")


@_facade().router.post("/admin/impersonate/end", response_model=None)
async def admin_end_impersonate(request: _facade().Request):
    from app.application.session_account_meta import (
        audit_admin_action,
        clear_impersonation,
        load_session_account_meta,
    )
    from app.enterprise.mod_entitlements import (
        persist_entitlements_to_session_row,
        refresh_session_entitlements_from_market,
        reload_enterprise_mods_after_login,
    )
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request
    from app.fastapi_routes.market_account import resolve_valid_market_access_token

    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    sid = _session_id_from_request(request)
    meta = load_session_account_meta(sid) or {}
    clear_impersonation(sid)
    tok = await resolve_valid_market_access_token(sid)
    if tok:
        client_ids = await refresh_session_entitlements_from_market(
            market_token=tok, market_user_id=meta.get("market_user_id"), session_id=sid
        )
        persist_entitlements_to_session_row(sid, client_ids)
        await reload_enterprise_mods_after_login()
    audit_admin_action(request, "impersonate_end")
    return {"success": True}


def _inject_digest_api_base(
    payload: dict[str, _facade().Any], base: str
) -> dict[str, _facade().Any]:
    """在 ``data`` 中写入 ``digest_api_base``，供 XCmax 页眉与「打开市场」与解锁校验同源提示。"""
    data = payload.get("data")
    if isinstance(data, dict):
        data["digest_api_base"] = base
    return payload


@_facade().router.get("/admin/digest-identity", response_model=None)
async def get_digest_identity(request: _facade().Request):
    """透传远端「身份校验码」摘要；与修茈市场 ``verify-admin-digest-code`` 同一实现源。"""
    from app.fastapi_routes.market_account import _market_base_url

    api_base = _market_base_url()
    out = await _facade()._market_admin_proxy(request, "GET", "/api/xcmax/admin/digest-identity")
    if isinstance(out, _facade().JSONResponse) and out.status_code == 404:
        _facade().logger.debug(
            "digest-identity: upstream 404, returning empty code payload for HTML fallback"
        )
        return {
            "success": True,
            "data": {
                "code": "",
                "expires_at": "",
                "valid": False,
                "daily_digest_id": None,
                "digest_api_base": api_base,
            },
        }
    if isinstance(out, dict):
        return _facade()._inject_digest_api_base(out, api_base)
    return out


@_facade().router.get("/release-train", response_model=None)
async def get_release_train():
    """release_train 四段 SSOT 快照（全景页 live 刷新，无需登录）。"""
    return {"success": True, "data": _facade()._release_train_snapshot()}


@_facade().router.get("/local/duty-graph/health", response_model=None)
async def local_duty_graph_health(request: _facade().Request):
    """本机编制图 health（不代理远端 MODstore）。"""
    from app.application.local_duty_graph_health import build_local_duty_graph_health
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

    if not _session_id_from_request(request):
        return _facade().JSONResponse({"success": False, "message": "请先登录"}, status_code=401)
    return build_local_duty_graph_health()


@_facade().router.get("/local/ops/self-maintenance/status", response_model=None)
async def local_self_maintenance_status(
    request: _facade().Request, limit: int = _facade().Query(default=80, ge=1, le=300)
):
    """本机自维护 loop runtime 状态（直连 MODstore :8788）。"""
    from app.application import self_maintenance_app_service as sm_svc
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request
    from app.fastapi_routes.market_account import _authorization_from_request

    if not _session_id_from_request(request):
        return _facade().JSONResponse({"success": False, "message": "请先登录"}, status_code=401)
    authorization = _authorization_from_request(request, {})
    try:
        return await sm_svc.get_runtime_status_local(limit=limit, authorization=authorization)
    except _facade().RECOVERABLE_ERRORS as exc:
        return _facade().JSONResponse({"success": False, "message": str(exc)}, status_code=502)


@_facade().router.post("/local/ops/self-maintenance/governance-review", response_model=None)
async def local_self_maintenance_governance_review(
    request: _facade().Request,
    body: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    """本机自维护 loop 治理审计复核。"""
    from app.application import self_maintenance_app_service as sm_svc
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request
    from app.fastapi_routes.market_account import _authorization_from_request

    if not _session_id_from_request(request):
        return _facade().JSONResponse({"success": False, "message": "请先登录"}, status_code=401)
    authorization = _authorization_from_request(request, body if isinstance(body, dict) else {})
    try:
        return await sm_svc.governance_review_local(
            note=str(body.get("note") or ""), authorization=authorization
        )
    except _facade().RECOVERABLE_ERRORS as exc:
        return _facade().JSONResponse({"success": False, "message": str(exc)}, status_code=502)


@_facade().router.get("/local/employee-cron/jobs", response_model=None)
async def local_employee_cron_jobs(request: _facade().Request):
    """本机员工定时任务列表（管理端点火状态）。"""
    from app.application.employee_runtime.scheduler import get_employee_cron_jobs
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

    if not _session_id_from_request(request):
        return _facade().JSONResponse({"success": False, "message": "请先登录"}, status_code=401)
    return {"success": True, "source": "local", "jobs": get_employee_cron_jobs()}


@_facade().router.post("/local/employee-cron/jobs/{job_id}/run", response_model=None)
async def local_employee_cron_job_run(
    request: _facade().Request,
    job_id: str,
    body: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    """手动触发本机员工定时任务，供管理端立即验证 daily 员工是否能跑。"""
    from app.application.employee_runtime.scheduler import run_employee_cron_job
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

    sid = _session_id_from_request(request)
    if not sid:
        return _facade().JSONResponse({"success": False, "message": "请先登录"}, status_code=401)
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
        return _facade().JSONResponse(result, status_code=404)
    return result


@_facade().router.get("/local/employees/{employee_id}/status", response_model=None)
async def local_employee_status(request: _facade().Request, employee_id: str):
    """本机员工包部署态与执行统计（编制图 Phase2，不代理 MODstore）。"""
    from app.application.local_duty_graph_health import build_local_employee_status
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

    if not _session_id_from_request(request):
        return _facade().JSONResponse({"success": False, "message": "请先登录"}, status_code=401)
    pid = str(employee_id or "").strip()
    if not pid:
        return _facade().JSONResponse(
            {"success": False, "message": "employee_id 必填"}, status_code=400
        )
    return build_local_employee_status(pid)


@_facade().router.post("/local/employees/{employee_id}/execute", response_model=None)
async def local_employee_execute(
    request: _facade().Request,
    employee_id: str,
    body: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
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
        return _facade().JSONResponse({"success": False, "message": "请先登录"}, status_code=401)
    user = resolve_session_user(request)
    if user is None:
        return _facade().JSONResponse({"success": False, "message": "请先登录"}, status_code=401)
    meta = enrich_session_meta_with_tenant(sid, user)
    require_allowed(
        user=user,
        account_kind=str(meta.get("account_kind") or "admin"),
        session_meta=meta,
        route=f"/local/employees/{employee_id}/execute",
    )
    pid = str(employee_id or "").strip()
    if not pid:
        return _facade().JSONResponse(
            {"success": False, "message": "employee_id 必填"}, status_code=400
        )
    task = str(body.get("task") or "").strip()
    if not task:
        return _facade().JSONResponse({"success": False, "message": "task 必填"}, status_code=400)
    raw_input = body.get("input_data")
    if raw_input is not None and (not isinstance(raw_input, dict)):
        return _facade().JSONResponse(
            {"success": False, "message": "input_data 必须是对象"}, status_code=400
        )
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
    result: dict[str, _facade().Any] = {"success": False, "message": "未执行"}
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


@_facade().router.get("/local/employees/{employee_id}/runs", response_model=None)
async def local_employee_runs(request: _facade().Request, employee_id: str, limit: int = 50):
    from app.application.employee_runtime.run_ledger import list_employee_run_logs
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

    if not _session_id_from_request(request):
        return _facade().JSONResponse({"success": False, "message": "请先登录"}, status_code=401)
    pid = str(employee_id or "").strip()
    if not pid:
        return _facade().JSONResponse(
            {"success": False, "message": "employee_id 必填"}, status_code=400
        )
    return {"success": True, "data": list_employee_run_logs(pid, limit=limit)}


@_facade().router.get("/local/employees/{employee_id}/manifest", response_model=None)
async def local_employee_manifest(request: _facade().Request, employee_id: str):
    """读本机 mods/_employees/<id>/manifest.json（编制图 LLM/依赖解析）。"""
    from app.application.local_duty_graph_health import read_local_employee_manifest
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

    if not _session_id_from_request(request):
        return _facade().JSONResponse({"success": False, "message": "请先登录"}, status_code=401)
    pid = str(employee_id or "").strip()
    if not pid:
        return _facade().JSONResponse(
            {"success": False, "message": "employee_id 必填"}, status_code=400
        )
    row = read_local_employee_manifest(pid)
    if not row:
        return _facade().JSONResponse(
            {"success": False, "message": f"员工包不存在: {pid}"}, status_code=404
        )
    return row


@_facade().router.get("/admin/modules", response_model=None)
async def list_modules():
    """获取 XCmax 模块注册表（核心 + 本地 Mod + 员工包）。"""
    modules: list[dict[str, _facade().Any]] = list(_facade().CORE_MODULES)
    modules.extend(_facade()._collect_mod_modules())
    modules.extend(_facade()._collect_employee_pack_modules())
    return {"success": True, "data": modules, "total": len(modules)}


@_facade().router.get("/admin/daily-digests", response_model=None)
async def list_daily_digests(
    request: _facade().Request,
    limit: int = _facade().Query(20, ge=1, le=100),
    offset: int = _facade().Query(0, ge=0),
):
    """从服务器读取已保存的每日摘要邮件副本。"""
    return await _facade()._digest_local_or_proxy(
        request, "GET", f"/api/xcmax/admin/daily-digests?limit={limit}&offset={offset}"
    )
