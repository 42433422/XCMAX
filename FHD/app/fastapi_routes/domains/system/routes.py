"""Migrated from legacy_system.py (v10)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

from app.template_analysis_progress import get_template_analysis_progress
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_utils import get_base_dir

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
        from app.utils.performance_initializer import get_performance_optimizer

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
        from app.utils.performance_initializer import get_performance_optimizer

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
        from app.utils.performance_initializer import get_performance_optimizer

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
        from app.utils.performance_initializer import get_performance_optimizer

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
        from app.utils.performance_initializer import get_performance_optimizer

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
def performance_tasks_status(task_id: str | None = Query(default=None)):
    try:
        from app.utils.performance_initializer import get_performance_optimizer

        optimizer = get_performance_optimizer()
        if not optimizer.async_task_manager:
            return JSONResponse(
                {"success": False, "message": "异步任务管理未启用", "data": None},
                status_code=503,
            )
        if task_id:
            result = optimizer.async_task_manager.get_status(task_id)
            if result is None:
                return JSONResponse(
                    {"success": False, "message": "任务不存在", "data": None},
                    status_code=404,
                )
            return {
                "success": True,
                "data": {
                    "task_id": result.task_id,
                    "status": result.status.value,
                    "progress": result.progress,
                    "duration_ms": round(result.duration_ms, 2) if result.duration_ms else None,
                    "error": result.error,
                    "metadata": result.metadata,
                },
            }
        active_tasks = optimizer.async_task_manager.active_tasks
        stats = optimizer.async_task_manager.stats
        return {
            "success": True,
            "data": {
                "active_tasks": (
                    {
                        tid: {
                            "task_id": t.task_id,
                            "status": t.status.value,
                            "progress": t.progress,
                            "name": t.metadata.get("task_name", ""),
                        }
                        for tid, t in (active_tasks or {}).items()
                    }
                    if active_tasks
                    else {}
                ),
                "stats": stats,
            },
        }
    except RECOVERABLE_ERRORS as e:
        return JSONResponse({"success": False, "message": str(e), "data": None}, status_code=500)


@router.get("/api/performance/alerts")
def performance_alerts(level: str | None = Query(default=None), limit: int = Query(default=20)):
    try:
        from app.utils.performance_initializer import get_performance_optimizer

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
        from app.utils.performance_initializer import get_performance_optimizer

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
):
    data, code = await _run_templates_analyze_agent(
        request=request,
        file=file,
        template_name=template_name,
        template_scope=template_scope,
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


def _user_id_from_tool_request(request: Request, body: dict[str, Any]) -> str:
    params = body.get("params") if isinstance(body.get("params"), dict) else {}
    return str(
        request.headers.get("X-User-Id")
        or request.headers.get("X-User-ID")
        or body.get("user_id")
        or body.get("userId")
        or params.get("user_id")
        or "tools-route"
    ).strip()


def _tool_route_agent_payload(run: Any, node_id: str) -> dict[str, Any]:
    final_output = getattr(run, "final_output", None)
    node_outputs = dict((final_output or {}).get("node_outputs") or {})
    output = dict(node_outputs.get(node_id) or {})
    if not output:
        for step in getattr(run, "steps", []) or []:
            if str(getattr(step, "node_id", "")) == node_id:
                output = dict(getattr(step, "output", {}) or {})
                if not output and str(getattr(step, "status", "")) == "waiting_user":
                    output = {
                        "success": True,
                        "message": "工具执行需要用户确认",
                        "waiting_step_id": getattr(step, "step_id", ""),
                    }
                break
    if not output:
        output = {"success": getattr(run, "status", "") in {"completed", "waiting_user"}}
    if not output.get("success") and getattr(run, "error", "") and not output.get("message"):
        output["message"] = getattr(run, "error", "")
    run_id = str(getattr(run, "run_id", "") or "")
    if run_id:
        output["run_id"] = run_id
        output["agent_run_id"] = run_id
    output["agent_status"] = str(getattr(run, "status", "") or "")
    output.setdefault("data", {})
    if isinstance(output.get("data"), dict):
        output["data"].setdefault("agent_run_id", run_id)
        output["data"].setdefault("run_id", run_id)
    return output


def _run_tools_execute_agent(
    *,
    request: Request,
    body: dict[str, Any],
    route_path: str,
) -> tuple[dict[str, Any], int] | None:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode
    from app.services.tools_execution.registry import _normalize_action, get_workflow_tool_registry

    raw_tool_id = body.get("tool_id") or body.get("skill_id")
    tool_id = str(raw_tool_id or "").strip()
    if not tool_id:
        return None
    params = body.get("params")
    if not isinstance(params, dict):
        params = {}
    action = _normalize_action(str(body.get("action") or "view"), params)
    registry = get_workflow_tool_registry()
    if tool_id not in registry or action not in dict(registry[tool_id].get("actions") or {}):
        return None

    node_id = f"tools_execute_{tool_id}_{action}".replace(".", "_").replace("-", "_")
    plan = PlanGraph(
        plan_id=f"tools_execute_{tool_id}_{action}",
        intent=f"tools_execute_{tool_id}_{action}",
        todo_steps=[f"通过 AgentOrchestrator 执行 {tool_id}.{action}"],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id=tool_id,
                action=action,
                params=dict(params),
                risk=str(registry[tool_id]["actions"][action].get("risk") or "low"),
                idempotent=bool(registry[tool_id]["actions"][action].get("idempotent", False)),
                description=f"Execute {tool_id}.{action} through the unified Agent runtime.",
            )
        ],
        risk_level=str(registry[tool_id]["actions"][action].get("risk") or "low"),
        metadata={"source": "tools_execute_route", "route": route_path},
    )
    user_id = _user_id_from_tool_request(request, body)
    run = AgentOrchestrator().start_run_from_plan(
        user_id=user_id,
        message=str(body.get("message") or f"Execute {tool_id}.{action}"),
        plan=plan,
        runtime_context={
            "source": "tools_execute_route",
            "route": route_path,
            "request_path": str(request.url.path),
            "user_id": user_id,
        },
    )
    payload = _tool_route_agent_payload(run, node_id)
    if run.status in {"waiting_user", "blocked"}:
        return payload, 202
    return payload, 200 if payload.get("success") else 400


async def _run_templates_analyze_agent(
    *,
    request: Request,
    file: UploadFile,
    template_name: str,
    template_scope: str,
) -> tuple[dict[str, Any], int]:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode
    from app.utils.upload_helpers import save_upload_file

    saved_path = await save_upload_file(file, subdir="template-analysis")
    node_id = "template_extract_analyze"
    params = {
        "file_path": saved_path,
        "template_name": str(template_name or ""),
        "template_scope": str(template_scope or ""),
    }
    plan = PlanGraph(
        plan_id="templates_analyze",
        intent="templates_analyze",
        todo_steps=["通过 AgentOrchestrator 分析上传模板文件"],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id="template_extract",
                action="extract",
                params=params,
                risk="low",
                idempotent=True,
                description="Analyze uploaded template structure through the unified Agent runtime.",
            )
        ],
        risk_level="low",
        metadata={
            "source": "templates_analyze_route",
            "route": "/api/templates/analyze",
            "artifacts": [
                {
                    "artifact_type": "excel_file",
                    "name": file.filename or "upload.bin",
                    "source": "templates_analyze_route",
                    "uri": saved_path,
                    "summary": "上传的模板分析源文件",
                    "fields": [
                        {"name": "template_name", "value": template_name},
                        {"name": "template_scope", "value": template_scope},
                    ],
                }
            ],
        },
    )
    user_id = _user_id_from_tool_request(request, {"params": params})
    run = AgentOrchestrator().start_run_from_plan(
        user_id=user_id,
        message=f"Analyze template: {file.filename or saved_path}",
        plan=plan,
        runtime_context={
            "source": "templates_analyze_route",
            "route": "/api/templates/analyze",
            "request_path": str(request.url.path),
            "user_id": user_id,
            "file_path": saved_path,
            "template_name": template_name,
            "template_scope": template_scope,
        },
    )
    payload = _tool_route_agent_payload(run, node_id)
    if run.status in {"waiting_user", "blocked"}:
        return payload, 202
    return payload, 200 if payload.get("success") else 400


def _run_system_maintenance_agent(
    *,
    request: Request,
    action: str,
    params: dict[str, Any],
    route_path: str,
) -> tuple[dict[str, Any], int]:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode
    from app.services.tools_execution.registry import get_workflow_tool_registry

    data = dict(params or {})
    registry = get_workflow_tool_registry()
    action_meta = dict((registry.get("system_maintenance") or {}).get("actions") or {}).get(action)
    if not isinstance(action_meta, dict):
        return {"success": False, "message": f"未注册的系统维护动作: {action}"}, 400

    node_id = f"system_maintenance_{action}"
    plan = PlanGraph(
        plan_id=node_id,
        intent=node_id,
        todo_steps=[f"通过 AgentOrchestrator 执行 system_maintenance.{action}"],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id="system_maintenance",
                action=action,
                params=data,
                risk=str(action_meta.get("risk") or "high"),
                idempotent=bool(action_meta.get("idempotent", False)),
                description=f"Execute system_maintenance.{action} through the unified Agent runtime.",
            )
        ],
        risk_level=str(action_meta.get("risk") or "high"),
        metadata={"source": "system_maintenance_route", "route": route_path},
    )
    user_id = _user_id_from_tool_request(request, data)
    runtime_context = {
        "source": "system_maintenance_route",
        "route": route_path,
        "request_path": str(request.url.path),
        "user_id": user_id,
        "route_confirmed": True,
    }
    orchestrator = AgentOrchestrator()
    run = orchestrator.start_run_from_plan(
        user_id=user_id,
        message=str(data.get("message") or f"System maintenance {action}"),
        plan=plan,
        runtime_context=runtime_context,
    )
    if run.status == "waiting_user":
        continued = orchestrator.continue_run(
            run.run_id,
            approved_by=user_id or "system-maintenance-route",
            runtime_context=runtime_context,
        )
        if continued is not None:
            run = continued
    payload = _tool_route_agent_payload(run, node_id)
    status_code = int(
        payload.pop("http_status_code", 0) or (200 if payload.get("success") else 400)
    )
    if payload.get("error_code") == "tool_exception":
        status_code = 500
    if run.status in {"waiting_user", "blocked"}:
        status_code = 202
    return payload, status_code


def _run_document_template_agent(
    *,
    request: Request,
    body: dict[str, Any],
    action: str,
    route_path: str,
) -> tuple[dict[str, Any], int]:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode
    from app.services.tools_execution.registry import get_workflow_tool_registry

    data = dict(body or {})
    registry = get_workflow_tool_registry()
    action_meta = dict((registry.get("document_template") or {}).get("actions") or {}).get(action)
    if not isinstance(action_meta, dict):
        return {"success": False, "message": f"未注册的模板动作: {action}"}, 400
    node_id = f"document_template_{action}"
    plan = PlanGraph(
        plan_id=f"document_template_{action}",
        intent=f"document_template_{action}",
        todo_steps=[f"通过 AgentOrchestrator 执行 document_template.{action}"],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id="document_template",
                action=action,
                params=data,
                risk=str(action_meta.get("risk") or "medium"),
                idempotent=bool(action_meta.get("idempotent", False)),
                description=f"Execute document_template.{action} through the unified Agent runtime.",
            )
        ],
        risk_level=str(action_meta.get("risk") or "medium"),
        metadata={"source": "document_template_route", "route": route_path},
    )
    user_id = _user_id_from_tool_request(request, data)
    runtime_context = {
        "source": "document_template_route",
        "route": route_path,
        "request_path": str(request.url.path),
        "user_id": user_id,
        "route_confirmed": True,
    }
    if action == "delete":
        template_id = str(data.get("id") or "").strip()
        if template_id.startswith("fs:") and template_id.split(":", 1)[1].strip():
            try:
                runtime_context["template_base_dir"] = get_base_dir()
            except RECOVERABLE_ERRORS as exc:
                return {"success": False, "message": f"删除失败：{str(exc)}"}, 500
    orchestrator = AgentOrchestrator()
    run = orchestrator.start_run_from_plan(
        user_id=user_id,
        message=str(data.get("message") or f"Template {action}"),
        plan=plan,
        runtime_context=runtime_context,
    )
    if run.status == "waiting_user":
        continued = orchestrator.continue_run(
            run.run_id,
            approved_by=user_id or "document-template-route",
            runtime_context=runtime_context,
        )
        if continued is not None:
            run = continued
    payload = _tool_route_agent_payload(run, node_id)
    status_code = int(
        payload.pop("http_status_code", 0) or (200 if payload.get("success") else 400)
    )
    if payload.get("error_code") == "tool_exception":
        status_code = 500
    if run.status in {"waiting_user", "blocked"}:
        status_code = 202
    return payload, status_code


@router.post("/api/skills/execute")
def skills_execute(request: Request, body: dict = Body(default_factory=dict)):
    agent_result = _run_tools_execute_agent(
        request=request,
        body=body or {},
        route_path="/api/skills/execute",
    )
    if agent_result is not None:
        return JSONResponse(agent_result[0], status_code=agent_result[1])
    from app.application.facades.tools_facade import run_archive_tools_execute

    data, code = run_archive_tools_execute(body)
    return JSONResponse(data, status_code=code)


@router.post("/api/tools/execute")
def tools_execute_route(request: Request, body: dict = Body(default_factory=dict)):
    agent_result = _run_tools_execute_agent(
        request=request,
        body=body or {},
        route_path="/api/tools/execute",
    )
    if agent_result is not None:
        return JSONResponse(agent_result[0], status_code=agent_result[1])
    from app.application.facades.tools_facade import run_archive_tools_execute

    data, code = run_archive_tools_execute(body)
    return JSONResponse(data, status_code=code)


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
