"""XCmax admin deploy/modules routes."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse

import app.fastapi_routes.xcmax_admin_patch as _p

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/release-train", response_model=None)
async def get_release_train():
    """release_train 四段 SSOT 快照（全景页 live 刷新，无需登录）。"""
    return {"success": True, "data": _p._release_train_snapshot()}
@router.get("/admin/modules", response_model=None)
async def list_modules():
    """获取 XCmax 模块注册表（核心 + 本地 Mod + 员工包）。"""
    modules: list[dict[str, Any]] = list(_p.CORE_MODULES)
    modules.extend(_p._collect_mod_modules())
    modules.extend(_p._collect_employee_pack_modules())
    return {"success": True, "data": modules, "total": len(modules)}
@router.get("/admin/remote-status", response_model=None)
async def remote_status():
    """探测远端服务器连接状态（轻量 HTTP GET /api/health）。"""
    return await asyncio.to_thread(_p._probe_remote_health_sync)

@router.get("/admin/deploy/check", response_model=None)
async def admin_deploy_check(request: Request, channel: str = Query("stable")):
    """管理端检查本地版本、update 中转站版本、企业端待更新状态。"""
    gate = _p._require_market_admin_session(request)
    if gate is not None:
        return gate
    normalized_channel = "staging" if str(channel).strip() == "staging" else "stable"
    from app.application.admin_deploy_push import check_deploy_updates

    data = await asyncio.to_thread(check_deploy_updates, normalized_channel)
    return {"success": True, "data": data}

@router.post("/admin/deploy/push", response_model=None)
async def admin_deploy_push(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    """管理端推送更新包到 update 中转站；企业端自行拉取。"""
    gate = _p._require_market_admin_session(request)
    if gate is not None:
        return gate
    payload = dict(body or {})
    channel = "staging" if str(payload.get("channel") or "").strip() == "staging" else "stable"
    options = {
        "include_backend": bool(payload.get("include_backend", True)),
        "include_frontend": bool(payload.get("include_frontend", True)),
        "skip_pack": bool(payload.get("skip_pack", False)),
        "channel": channel,
    }
    ssh_key = str(payload.get("ssh_key") or "").strip()
    if ssh_key:
        options["ssh_key"] = ssh_key
    try:
        from app.application.admin_deploy_push import start_deploy_push

        job = await start_deploy_push(options)
        return {"success": True, "data": job.to_dict()}
    except _p.RECOVERABLE_ERRORS as exc:
        logger.warning("admin deploy push failed to start: %s", exc)
        return JSONResponse({"success": False, "message": str(exc)}, status_code=409)

@router.get("/admin/deploy/jobs/{job_id}", response_model=None)
async def admin_deploy_job(request: Request, job_id: str):
    """查询管理端更新包推送任务。"""
    gate = _p._require_market_admin_session(request)
    if gate is not None:
        return gate
    normalized_job_id = "".join(ch for ch in str(job_id or "") if ch.isalnum() or ch in "-_")[:128]
    if not normalized_job_id:
        return JSONResponse({"success": False, "message": "job_id 无效"}, status_code=400)
    from app.application.admin_deploy_push import get_deploy_job

    job = get_deploy_job(normalized_job_id)
    if job is None:
        return JSONResponse({"success": False, "message": "推送任务不存在"}, status_code=404)
    return {"success": True, "data": job.to_dict()}
