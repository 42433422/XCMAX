"""Migrated from legacy_system.py (v10)."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Body, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

from app.fastapi_routes.domains.system.agent_handlers import (
    run_document_template_agent as _run_document_template_agent,
)
from app.fastapi_routes.domains.system.agent_handlers import (
    run_system_maintenance_agent as _run_system_maintenance_agent,
)
from app.fastapi_routes.domains.system.agent_handlers import (
    run_templates_analyze_agent as _run_templates_analyze_agent,
)
from app.fastapi_routes.domains.system.performance_handlers import (
    performance_tasks_status_payload,
)
from app.template_analysis_progress import get_template_analysis_progress
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import get_base_dir as get_base_dir

logger = logging.getLogger(__name__)

router = APIRouter(tags=["legacy-system"], deprecated=True)


@router.get("/api/system/config")
def system_config_get():
    try:
        from resources.config import industry_config as ic

        return {
            "success": True,
            "data": {
                "current_industry": ic.get_current_industry(),
                "available_industries": ic.get_available_industries(),
            },
        }
    except RECOVERABLE_ERRORS as e:
        logger.exception("system config: %s", e)
        return {
            "success": True,
            "data": {
                "current_industry": "涂料",
                "available_industries": [{"id": "涂料", "name": "涂料/油漆行业"}],
                "degraded": True,
                "hint": (str(e) or "error")[:300],
            },
        }


@router.get("/api/system/info")
def system_info_get():
    try:
        from app.application.facades.session_facade import get_system_service

        return {"success": True, "data": get_system_service().get_system_info()}
    except RECOVERABLE_ERRORS as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.get("/api/system/printer")
def system_printer_get():
    try:
        from app.application.facades.session_facade import get_system_service

        return {"success": True, "data": get_system_service().get_printer_config()}
    except RECOVERABLE_ERRORS as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.post("/api/system/printer")
def system_printer_post(request: Request, body: dict = Body(default_factory=dict)):
    data, code = _run_system_maintenance_agent(
        request=request,
        action="set_default_printer",
        params=dict(body or {}),
        route_path="/api/system/printer",
    )
    return JSONResponse(data, status_code=code)


@router.get("/api/system/startup")
def system_startup_get():
    try:
        from app.application.facades.session_facade import get_system_service

        return {"success": True, "data": get_system_service().get_startup_config()}
    except RECOVERABLE_ERRORS as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.post("/api/system/startup")
def system_startup_post(request: Request):
    data, code = _run_system_maintenance_agent(
        request=request,
        action="enable_startup",
        params={},
        route_path="/api/system/startup",
    )
    return JSONResponse(data, status_code=code)


@router.delete("/api/system/startup")
def system_startup_delete(request: Request):
    data, code = _run_system_maintenance_agent(
        request=request,
        action="disable_startup",
        params={},
        route_path="/api/system/startup",
    )
    return JSONResponse(data, status_code=code)


@router.get("/api/database/backups")
def database_backups_list():
    try:
        from app.application.facades.session_facade import get_database_service

        return get_database_service().list_backups()
    except RECOVERABLE_ERRORS as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.delete("/api/database/backup/{backup_file:path}")
def database_backup_delete(request: Request, backup_file: str):
    data, code = _run_system_maintenance_agent(
        request=request,
        action="delete_database_backup",
        params={"backup_file": backup_file},
        route_path="/api/database/backup/{backup_file}",
    )
    return JSONResponse(data, status_code=code)


@router.post("/api/database/backup")
def database_backup(request: Request):
    data, code = _run_system_maintenance_agent(
        request=request,
        action="backup_database",
        params={},
        route_path="/api/database/backup",
    )
    return JSONResponse(data, status_code=code)


@router.post("/api/database/restore")
def database_restore(request: Request, body: dict = Body(default_factory=dict)):
    data, code = _run_system_maintenance_agent(
        request=request,
        action="restore_database",
        params=dict(body or {}),
        route_path="/api/database/restore",
    )
    return JSONResponse(data, status_code=code)


@router.get("/api/performance/status")
def performance_status():
    import time as _time

    try:
        from app.utils.performance.performance_initializer import get_performance_optimizer

        optimizer = get_performance_optimizer()
        if not optimizer._initialized:
            return JSONResponse(
                {"success": False, "message": "性能优化系统未初始化", "data": None},
                status_code=503,
            )
        return {"success": True, "data": optimizer.get_status(), "timestamp": _time.time()}
    except RECOVERABLE_ERRORS as e:
        return JSONResponse({"success": False, "message": str(e), "data": None}, status_code=500)


@router.get("/api/performance/health")
def performance_health():
    import time as _time

    try:
        from app.utils.performance.performance_initializer import get_performance_optimizer

        optimizer = get_performance_optimizer()
        health = optimizer.get_health_check()
        code = (
            200
            if health["status"] == "healthy"
            else (503 if health["status"] == "degraded" else 500)
        )
        resp = {
            "status": health["status"],
            "timestamp": health["timestamp"],
            "checks": health.get("checks", {}),
        }
        if "issues" in health:
            resp["issues"] = health["issues"]
        return JSONResponse(resp, status_code=code)
    except RECOVERABLE_ERRORS as e:
        return JSONResponse(
            {"status": "unhealthy", "error": str(e), "timestamp": _time.time()},
            status_code=500,
        )


@router.get("/api/performance/metrics/summary")
def performance_metrics_summary(minutes: int = Query(default=5)):
    try:
        minutes = max(1, min(minutes, 60))
        from app.utils.performance.performance_initializer import get_performance_optimizer

        optimizer = get_performance_optimizer()
        if not optimizer.performance_monitor:
            return JSONResponse(
                {"success": False, "message": "性能监控未启用", "data": None},
                status_code=503,
            )
        summary = optimizer.performance_monitor.get_metrics_summary(minutes=minutes)
        return {"success": True, "data": summary}
    except RECOVERABLE_ERRORS as e:
        return JSONResponse({"success": False, "message": str(e), "data": None}, status_code=500)


@router.get("/api/performance/metrics/prometheus")
def performance_metrics_prometheus():
    try:
        from app.utils.performance.performance_initializer import get_performance_optimizer

        optimizer = get_performance_optimizer()
        if not optimizer.performance_monitor:
            return PlainTextResponse("# XCAGI metrics unavailable\n", status_code=503)
        return PlainTextResponse(
            optimizer.performance_monitor.get_prometheus_metrics(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )
    except RECOVERABLE_ERRORS as e:
        return PlainTextResponse(f"# Error: {str(e)}\n", status_code=500)


@router.get("/api/performance/cache/stats")
def performance_cache_stats():
    try:
        from app.utils.performance.performance_initializer import get_performance_optimizer

        optimizer = get_performance_optimizer()
        if not optimizer.redis_cache:
            return JSONResponse(
                {"success": False, "message": "Redis 缓存未初始化", "data": None},
                status_code=503,
            )
        return {"success": True, "data": optimizer.redis_cache.stats}
    except RECOVERABLE_ERRORS as e:
        return JSONResponse({"success": False, "message": str(e), "data": None}, status_code=500)


@router.post("/api/performance/cache/clear")
def performance_cache_clear(request: Request, pattern: str | None = Query(default=None)):
    data, code = _run_system_maintenance_agent(
        request=request,
        action="clear_performance_cache",
        params={"pattern": pattern} if pattern else {},
        route_path="/api/performance/cache/clear",
    )
    return JSONResponse(data, status_code=code)


@router.post("/api/performance/cache/invalidate")
def performance_cache_invalidate(request: Request, body: dict = Body(default_factory=dict)):
    data, code = _run_system_maintenance_agent(
        request=request,
        action="invalidate_performance_cache",
        params=dict(body or {}),
        route_path="/api/performance/cache/invalidate",
    )
    return JSONResponse(data, status_code=code)


@router.get("/api/performance/tasks/status")
def performance_tasks_status(task_id: Annotated[str | None, Query()] = None):
    return performance_tasks_status_payload(task_id)


@router.get("/api/performance/alerts")
def performance_alerts(level: str | None = Query(default=None), limit: int = Query(default=20)):
    try:
        from app.utils.performance.performance_initializer import get_performance_optimizer

        optimizer = get_performance_optimizer()
        if not optimizer.performance_monitor:
            return JSONResponse(
                {"success": False, "message": "性能监控未启用", "data": []},
                status_code=503,
            )
        alerts = optimizer.performance_monitor.get_alerts(level=level, limit=limit)
        return {"success": True, "data": alerts, "count": len(alerts)}
    except RECOVERABLE_ERRORS as e:
        return JSONResponse({"success": False, "message": str(e), "data": []}, status_code=500)


@router.get("/api/performance/slow-queries")
def performance_slow_queries(limit: int = Query(default=20)):
    try:
        from app.utils.performance.performance_initializer import get_performance_optimizer

        optimizer = get_performance_optimizer()
        if not optimizer.query_optimizer:
            return JSONResponse(
                {"success": False, "message": "查询优化器未启用", "data": []},
                status_code=503,
            )
        slow = optimizer.query_optimizer.get_slow_queries(limit=limit)
        return {"success": True, "data": slow, "count": len(slow)}
    except RECOVERABLE_ERRORS as e:
        return JSONResponse({"success": False, "message": str(e), "data": []}, status_code=500)


@router.post("/api/performance/optimize/reinitialize")
def performance_optimize_reinitialize(request: Request):
    data, code = _run_system_maintenance_agent(
        request=request,
        action="reinitialize_performance",
        params={},
        route_path="/api/performance/optimize/reinitialize",
    )
    return JSONResponse(data, status_code=code)


@router.get("/api/templates/progress/{task_id}")
def templates_progress(task_id: str):
    return get_template_analysis_progress(task_id)


@router.delete("/api/templates/delete")
def templates_delete(request: Request, body: dict = Body(default_factory=dict)):
    data = dict(body or {})
    if not data.get("id") and request.query_params.get("id"):
        data["id"] = request.query_params.get("id")
    payload, code = _run_document_template_agent(
        request=request,
        body=data,
        action="delete",
        route_path="/api/templates/delete",
    )
    return JSONResponse(payload, status_code=code)


@router.post("/api/templates/create")
def templates_create(request: Request, body: dict = Body(default_factory=dict)):
    data, code = _run_document_template_agent(
        request=request,
        body=body,
        action="create",
        route_path="/api/templates/create",
    )
    return JSONResponse(data, status_code=code)


@router.post("/api/templates/update")
def templates_update(request: Request, body: dict = Body(default_factory=dict)):
    data, code = _run_document_template_agent(
        request=request,
        body=body,
        action="update",
        route_path="/api/templates/update",
    )
    return JSONResponse(data, status_code=code)


@router.post("/api/templates/delete")
def templates_delete_post(request: Request, body: dict = Body(default_factory=dict)):
    return templates_delete(request, body)


@router.post("/api/templates/analyze")
async def templates_analyze(
    request: Request,
    file: UploadFile = File(...),
    template_name: str = Form(default=""),
    template_scope: str = Form(default=""),
    auto_save: str = Form(default="0"),
):
    """解析办公模板；``auto_save=1`` 时直接写入模版库（等同 upload）。"""
    if str(auto_save or "").strip().lower() in {"1", "true", "yes", "on"}:
        raw = await file.read()
        from app.application.office_template_ingest_app_service import (
            ingest_office_bytes_to_template_library,
        )

        data, code = ingest_office_bytes_to_template_library(
            file_body=raw,
            filename=str(file.filename or "upload.bin"),
            template_name=template_name,
            template_scope=template_scope,
            source="templates_analyze_auto_save",
        )
        return JSONResponse(data, status_code=code)

    data, code = await _run_templates_analyze_agent(
        request=request,
        file=file,
        template_name=template_name,
        template_scope=template_scope,
    )
    return JSONResponse(data, status_code=code)


@router.post("/api/templates/upload")
async def templates_upload(
    file: UploadFile = File(...),
    template_name: str = Form(default=""),
    name: str = Form(default=""),
    template_scope: str = Form(default=""),
    type: str = Form(default=""),
    source: str = Form(default="office_upload"),
):
    """办公文件入口：解析并自动入库模版库（analyze → create）。"""
    from app.application.office_template_ingest_app_service import (
        ingest_office_bytes_to_template_library,
    )

    raw = await file.read()
    display_name = str(template_name or name or "").strip()
    scope = str(template_scope or type or "").strip()
    # 文档历史参数 type=excel|word|logo 不是 business_scope，避免误触发词条校验
    if scope.lower() in {"excel", "word", "logo", "label", "image"}:
        scope = ""
    data, code = ingest_office_bytes_to_template_library(
        file_body=raw,
        filename=str(file.filename or "upload.bin"),
        template_name=display_name,
        template_scope=scope,
        source=str(source or "office_upload").strip() or "office_upload",
    )
    return JSONResponse(data, status_code=code)


@router.get("/api/skills/list")
def skills_list():
    try:
        from app.infrastructure.skills import get_skill_registry

        registry = get_skill_registry()
        return {"success": True, "skills": registry.list_all()}
    except RECOVERABLE_ERRORS as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.get("/api/skills/info/{skill_id}")
def skills_info(skill_id: str):
    try:
        from app.infrastructure.skills import get_skill_registry

        registry = get_skill_registry()
        skill_info = registry.get(skill_id)
        if skill_info:
            return {
                "success": True,
                "skill": {
                    "id": skill_id,
                    "name": skill_info.get("name", ""),
                    "description": skill_info.get("description", ""),
                    "keywords": skill_info.get("keywords", []),
                    "category": skill_info.get("category", "general"),
                },
            }
        return JSONResponse({"success": False, "message": "技能不存在"}, status_code=404)
    except RECOVERABLE_ERRORS as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.post("/api/admin/llm/reload")
async def admin_llm_reload() -> JSONResponse:
    """热切换：清空进程内 LLM Provider 注册表。"""
    import os

    from app.infrastructure.llm.providers import registry as reg_mod

    reg_mod._registry = None
    return JSONResponse(
        {
            "success": True,
            "LLM_PROVIDER": (os.environ.get("LLM_PROVIDER") or "").strip(),
            "LLM_ROUTING_ORDER": (os.environ.get("LLM_ROUTING_ORDER") or "").strip(),
        }
    )
