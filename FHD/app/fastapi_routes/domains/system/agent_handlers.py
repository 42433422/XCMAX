"""Agent-backed execution helpers for legacy system routes."""

from __future__ import annotations

from typing import Any

from fastapi import Request, UploadFile

from app.application.workflow.types import normalize_workflow_risk
from app.fastapi_routes.tools_execute import (
    tool_route_agent_payload as _tool_route_agent_payload,
)
from app.fastapi_routes.tools_execute import (
    user_id_from_tool_request as _user_id_from_tool_request,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


async def run_templates_analyze_agent(
    *,
    request: Request,
    file: UploadFile,
    template_name: str,
    template_scope: str,
) -> tuple[dict[str, Any], int]:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode
    from app.utils.path_io.upload_helpers import save_upload_file

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


def run_system_maintenance_agent(
    *,
    request: Request,
    action: str,
    params: dict[str, Any],
    route_path: str,
) -> tuple[dict[str, Any], int]:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode
    from app.application.workflow_registry_app import get_workflow_tool_registry

    data = dict(params or {})
    registry = get_workflow_tool_registry()
    action_meta = dict((registry.get("system_maintenance") or {}).get("actions") or {}).get(action)
    if not isinstance(action_meta, dict):
        return {"success": False, "message": f"未注册的系统维护动作: {action}"}, 400

    node_id = f"system_maintenance_{action}"
    risk = normalize_workflow_risk(str(action_meta.get("risk") or "high"))
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
                risk=risk,
                idempotent=bool(action_meta.get("idempotent", False)),
                description=f"Execute system_maintenance.{action} through the unified Agent runtime.",
            )
        ],
        risk_level=risk,
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
    if run.status in {"waiting_user", "running"}:
        continued = orchestrator.continue_run(
            run.run_id,
            approved_by=user_id or "system-maintenance-route",
            approved_step_id=node_id,
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


def run_document_template_agent(
    *,
    request: Request,
    body: dict[str, Any],
    action: str,
    route_path: str,
) -> tuple[dict[str, Any], int]:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode
    from app.application.workflow_registry_app import get_workflow_tool_registry

    data = dict(body or {})
    registry = get_workflow_tool_registry()
    action_meta = dict((registry.get("document_template") or {}).get("actions") or {}).get(action)
    if not isinstance(action_meta, dict):
        return {"success": False, "message": f"未注册的模板动作: {action}"}, 400
    node_id = f"document_template_{action}"
    risk = normalize_workflow_risk(str(action_meta.get("risk") or "medium"))
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
                risk=risk,
                idempotent=bool(action_meta.get("idempotent", False)),
                description=f"Execute document_template.{action} through the unified Agent runtime.",
            )
        ],
        risk_level=risk,
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
                # Keep the historical patch point on the public route module.
                from app.fastapi_routes.domains.system import routes as route_facade

                runtime_context["template_base_dir"] = route_facade.get_base_dir()
            except RECOVERABLE_ERRORS:
                return {"success": False, "message": "删除模板失败"}, 500
    orchestrator = AgentOrchestrator()
    run = orchestrator.start_run_from_plan(
        user_id=user_id,
        message=str(data.get("message") or f"Template {action}"),
        plan=plan,
        runtime_context=runtime_context,
    )
    if run.status in {"waiting_user", "running"}:
        continued = orchestrator.continue_run(
            run.run_id,
            approved_by=user_id or "document-template-route",
            approved_step_id=node_id,
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
