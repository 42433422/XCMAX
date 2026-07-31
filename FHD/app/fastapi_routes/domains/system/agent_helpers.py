"""Extracted helpers for an existing public module."""

from __future__ import annotations

from app.utils.agent_route_status import agent_route_http_status
from app.utils.mixin_module_sync import sync_module_functions


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


def _authenticated_owner_user_id(request: Request) -> int | None:
    """Return the middleware-authenticated owner id, never client input.

    ``/api/tools/execute`` retains its legacy header/body user id for agent-run
    tracing, but a private ETL-derived document template must only be selected
    with the authenticated request identity injected by
    :class:`IndustryContextMiddleware`.  In particular, do not promote
    ``X-User-Id`` or a JSON ``user_id`` into this value.
    """

    try:
        value = getattr(request.state, "user_id", None)
        owner_user_id = int(value) if value is not None else 0
    except (AttributeError, TypeError, ValueError):
        return None
    return owner_user_id if owner_user_id > 0 else None


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
    from app.application.workflow_registry_app import _normalize_action, get_workflow_tool_registry

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
    owner_user_id = _authenticated_owner_user_id(request)
    # The authenticated owner is authoritative whenever it is available.  The
    # header/body fallback below remains only for old unauthenticated routes'
    # AgentRun attribution; it is deliberately not used for private templates.
    user_id = (
        str(owner_user_id)
        if owner_user_id is not None
        else _user_id_from_tool_request(request, body)
    )
    runtime_context = {
        "source": "tools_execute_route",
        "route": route_path,
        "request_path": str(request.url.path),
        "user_id": user_id,
    }
    if owner_user_id is not None:
        runtime_context["owner_user_id"] = owner_user_id
    run = AgentOrchestrator().start_run_from_plan(
        user_id=user_id,
        message=str(body.get("message") or f"Execute {tool_id}.{action}"),
        plan=plan,
        runtime_context=runtime_context,
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
    from app.application.workflow_registry_app import get_workflow_tool_registry

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
    status_code = agent_route_http_status(payload)
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
    from app.application.workflow_registry_app import get_workflow_tool_registry

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
    status_code = agent_route_http_status(payload)
    if run.status in {"waiting_user", "blocked"}:
        status_code = 202
    return payload, status_code


sync_module_functions(
    target=globals(),
    source_module="app.fastapi_routes.domains.system.routes",
    function_names=(
        "_user_id_from_tool_request",
        "_authenticated_owner_user_id",
        "_tool_route_agent_payload",
        "_run_tools_execute_agent",
        "_run_templates_analyze_agent",
        "_run_system_maintenance_agent",
        "_run_document_template_agent",
    ),
)
