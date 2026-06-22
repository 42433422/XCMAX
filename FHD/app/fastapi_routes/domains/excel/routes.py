"""Migrated from legacy_excel.py (v10)."""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from fastapi import APIRouter, Body, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_utils import get_upload_dir

logger = logging.getLogger(__name__)

router = APIRouter(tags=["legacy-excel"], deprecated=True)


def _trace_excel_route(
    payload: dict[str, Any],
    *,
    route: str,
    message: str,
    user_id: str = "",
    intent: str = "excel_ai_route",
    runtime_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("run_id") or payload.get("agent_run_id"):
        return payload
    try:
        from app.application.agent_orchestrator.chat_trace import create_chat_trace_run

        runtime = {
            "route": route,
            "source": "legacy_excel_route",
            **(runtime_context or {}),
        }
        run = create_chat_trace_run(
            payload,
            message=message,
            runtime_context=runtime,
            user_id=user_id or "legacy-excel-route",
            source="legacy_excel_route",
            channel="excel_ai_route",
            intent=intent,
        )
    except Exception:  # noqa: BLE001 - tracing must not break legacy AI routes
        logger.exception("failed to attach AgentRun trace to excel route response")
        return payload
    traced = dict(payload)
    traced["run_id"] = run.run_id
    traced["agent_run_id"] = run.run_id
    return traced


def _agent_node_payload(run: Any, node_id: str) -> dict[str, Any]:
    final_output = getattr(run, "final_output", None)
    node_outputs = dict((final_output or {}).get("node_outputs") or {})
    output = dict(node_outputs.get(node_id) or {})
    if not output:
        for step in getattr(run, "steps", []) or []:
            if str(getattr(step, "node_id", "")) == node_id:
                output = dict(getattr(step, "output", {}) or {})
                break
    if not output:
        output = {"success": getattr(run, "status", "") == "completed"}
    if not output.get("success") and getattr(run, "error", "") and not output.get("message"):
        output["message"] = getattr(run, "error", "")
    run_id = str(getattr(run, "run_id", "") or "")
    if run_id:
        output["run_id"] = run_id
        output["agent_run_id"] = run_id
    output["agent_status"] = str(getattr(run, "status", "") or "")
    if isinstance(output.get("data"), dict):
        output["data"].setdefault("run_id", run_id)
        output["data"].setdefault("agent_run_id", run_id)
    return output


def _user_id_from_excel_skill_request(request: Request, body: dict[str, Any]) -> str:
    return str(
        request.headers.get("X-User-Id")
        or request.headers.get("X-User-ID")
        or body.get("user_id")
        or body.get("userId")
        or "excel-skill-route"
    ).strip()


def _run_excel_skill_agent(
    *,
    request: Request,
    body: dict[str, Any],
    route_path: str,
    tool_id: str,
    action: str,
    params: dict[str, Any],
    intent: str,
    message: str,
) -> dict[str, Any]:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode
    from app.services.tools_execution.registry import get_workflow_tool_registry

    registry = get_workflow_tool_registry()
    action_meta = dict((registry.get(tool_id) or {}).get("actions") or {}).get(action)
    if not isinstance(action_meta, dict):
        return {"success": False, "message": f"未注册的工具动作: {tool_id}.{action}"}

    node_id = f"{intent}_{tool_id}_{action}".replace(".", "_").replace("-", "_")
    plan = PlanGraph(
        plan_id=intent,
        intent=intent,
        todo_steps=[f"通过 AgentOrchestrator 执行 {tool_id}.{action}"],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id=tool_id,
                action=action,
                params=dict(params),
                risk=str(action_meta.get("risk") or "low"),
                idempotent=bool(action_meta.get("idempotent", False)),
                description=f"Execute {tool_id}.{action} through the unified Agent runtime.",
            )
        ],
        risk_level=str(action_meta.get("risk") or "low"),
        metadata={"source": "excel_skill_route", "route": route_path},
    )
    user_id = _user_id_from_excel_skill_request(request, body)
    run = AgentOrchestrator().start_run_from_plan(
        user_id=user_id,
        message=message,
        plan=plan,
        runtime_context={
            "source": "excel_skill_route",
            "route": route_path,
            "request_path": str(request.url.path),
            "user_id": user_id,
        },
    )
    return _agent_node_payload(run, node_id)


@router.post("/api/ai/parse-single")
def ai_parse_single(body: dict = Body(default_factory=dict)):
    from app.application.facades.excel_facade import get_ai_product_parser

    data = body or {}
    text = data.get("text", "") or ""
    if not text.strip():
        return JSONResponse(
            {
                "success": False,
                "message": "text 不能为空",
                "missing_fields": ["unit", "quantity", "specification", "product"],
                "invalid_reason": "输入为空，无法解析",
            },
            status_code=400,
        )
    parser = get_ai_product_parser()
    result = parser.parse_single(
        text,
        use_ai=bool(data.get("use_ai", True)),
        fallback_to_rule=bool(data.get("fallback_to_rule", True)),
    )
    result = _trace_excel_route(
        result,
        route="/api/ai/parse-single",
        message=text,
        user_id=str(data.get("user_id") or data.get("userId") or ""),
        intent="excel_parse_single",
        runtime_context={
            "use_ai": bool(data.get("use_ai", True)),
            "fallback_to_rule": bool(data.get("fallback_to_rule", True)),
        },
    )
    return JSONResponse(result, status_code=200 if result.get("success") else 422)


@router.post("/api/ai/parse-products")
def ai_parse_products(body: dict = Body(default_factory=dict)):
    from app.application.facades.excel_facade import get_ai_product_parser

    data = body or {}
    texts = data.get("texts") or []
    if not isinstance(texts, list) or not texts:
        return JSONResponse({"success": False, "message": "texts 必须为非空数组"}, status_code=400)
    parser = get_ai_product_parser()
    result = parser.parse_batch(
        texts,
        use_ai=bool(data.get("use_ai", True)),
        fallback_to_rule=bool(data.get("fallback_to_rule", True)),
    )
    return _trace_excel_route(
        result,
        route="/api/ai/parse-products",
        message="\n".join(str(item) for item in texts[:5]),
        user_id=str(data.get("user_id") or data.get("userId") or ""),
        intent="excel_parse_products",
        runtime_context={
            "text_count": len(texts),
            "use_ai": bool(data.get("use_ai", True)),
            "fallback_to_rule": bool(data.get("fallback_to_rule", True)),
        },
    )


@router.post("/api/ai/analyze")
async def ai_analyze_post(
    query: str = Form(default=""),
    file: UploadFile | None = File(default=None),
):
    try:
        from app.application.facades.conversation_facade import get_data_analysis_service
        from app.utils.secure_filename import secure_filename as _sf

        service = get_data_analysis_service()
        if file is not None and file.filename:
            upload_dir = get_upload_dir()
            os.makedirs(upload_dir, exist_ok=True)
            filename = _sf(file.filename)
            file_path = os.path.join(upload_dir, f"{uuid.uuid4().hex[:8]}_{filename}")
            content = await file.read()
            with open(file_path, "wb") as f:
                f.write(content)
            try:
                result = service.analyze_file(file_path, query)
                return _trace_excel_route(
                    result,
                    route="/api/ai/analyze",
                    message=query or f"分析文件 {file.filename}",
                    user_id="legacy-excel-route",
                    intent="excel_data_analysis",
                    runtime_context={
                        "filename": str(file.filename or ""),
                        "query": str(query or ""),
                    },
                )
            finally:
                try:
                    os.unlink(file_path)
                except OSError:
                    pass
        if (query or "").strip():
            return _trace_excel_route(
                {
                    "success": True,
                    "file_info": {"rows": 0, "columns": []},
                    "statistics": {},
                    "chart_data": {
                        "type": "line",
                        "labels": ["1月", "2月", "3月", "4月"],
                        "datasets": [
                            {
                                "label": "销量",
                                "data": [1200, 1900, 1500, 2300],
                                "borderColor": "#3b82f6",
                            }
                        ],
                    },
                    "insights": ["已理解查询意图", "生成趋势分析"],
                    "message": "文本查询分析完成",
                    "response": "文本查询分析完成",
                },
                route="/api/ai/analyze",
                message=query,
                user_id="legacy-excel-route",
                intent="excel_data_analysis",
                runtime_context={"query": str(query or "")},
            )
        return JSONResponse({"success": False, "message": "请提供文件或查询内容"}, status_code=400)
    except RECOVERABLE_ERRORS as e:
        logger.exception("ai analyze: %s", e)
        return JSONResponse({"success": False, "message": f"服务器错误: {str(e)}"}, status_code=500)


@router.post("/api/ai/file/analyze")
async def ai_file_analyze(
    file: UploadFile | None = File(default=None),
    purpose: str = Form(default="general"),
    dataset_id: str = Form(default=""),
    tenant_id: str = Form(default=""),
    user_id: str = Form(default=""),
):
    try:
        from app.application import get_file_analysis_app_service
        from app.application.agent_orchestrator.chat_trace import attach_chat_trace_run

        if file is None or not file.filename:
            return JSONResponse({"success": False, "message": "未选择文件"}, status_code=400)
        raw = await file.read()

        class _UploadShim:
            def __init__(self, name: str, data: bytes):
                self.filename = name
                self._data = data

            def save(self, path: str) -> None:
                with open(path, "wb") as f:
                    f.write(self._data)

        service = get_file_analysis_app_service()
        result = service.analyze_file(_UploadShim(file.filename, raw), purpose)
        trace_payload = {
            "success": bool(result.get("success")),
            "response": str(result.get("message") or result.get("ai_summary") or "文件分析完成"),
            "data": {
                "text": str(result.get("message") or result.get("ai_summary") or "文件分析完成"),
                "file_analysis": dict(result),
            },
        }
        traced = attach_chat_trace_run(
            trace_payload,
            message=f"分析文件 {file.filename}",
            runtime_context={
                "route": "/api/ai/file/analyze",
                "source": "legacy_excel_route",
                "purpose": str(purpose or ""),
                "filename": str(file.filename or ""),
                "dataset_id": str(dataset_id or "").strip(),
                "tenant_id": str(tenant_id or "").strip(),
            },
            user_id=str(user_id or tenant_id or "legacy-excel-route"),
            source="legacy_excel_route",
            channel="file_analysis_route",
            intent="file_analysis",
        )
        run_id = str(traced.get("run_id") or traced.get("agent_run_id") or "").strip()
        if run_id:
            result["run_id"] = run_id
            result["agent_run_id"] = run_id
            data = result.get("data")
            if isinstance(data, dict):
                data.setdefault("run_id", run_id)
                data.setdefault("agent_run_id", run_id)
        return JSONResponse(result, status_code=200 if result.get("success") else 400)
    except RECOVERABLE_ERRORS as e:
        return JSONResponse(
            {"success": False, "message": f"文件分析失败：{str(e)}"}, status_code=500
        )


@router.post("/api/ai/sqlite/import_unit_products")
def ai_sqlite_import_unit_products(body: dict = Body(default_factory=dict)):
    try:
        from app.application.agent_orchestrator import AgentOrchestrator
        from app.application.agent_orchestrator.tool_spec import validate_tool_call
        from app.application.workflow.types import PlanGraph, WorkflowNode

        data = body or {}
        saved_name = str(data.get("saved_name") or "").strip()
        unit_name = str(data.get("unit_name") or data.get("unit_name_guess") or "").strip()
        params = {
            "saved_name": saved_name,
            "unit_name": unit_name,
            "create_purchase_unit": bool(data.get("create_purchase_unit", True)),
            "skip_duplicates": bool(data.get("skip_duplicates", True)),
        }
        validation = validate_tool_call("unit_products_import", "execute_import", params)
        if not validation.ok:
            return JSONResponse(
                {
                    "success": False,
                    "message": validation.message or "unit_products_import 参数无效",
                    "error_code": validation.error_code,
                },
                status_code=400,
            )

        plan = PlanGraph(
            plan_id=f"plan_route_unit_products_import_{uuid.uuid4().hex[:12]}",
            intent="import_unit_products_db",
            todo_steps=[
                "确认导入单位产品数据库",
                "执行 unit_products_import.execute_import",
                "记录导入结果和工具审计",
            ],
            nodes=[
                WorkflowNode(
                    node_id="import_unit_products",
                    tool_id="unit_products_import",
                    action="execute_import",
                    params=params,
                    risk="medium",
                    idempotent=False,
                    description="从 /api/ai/sqlite/import_unit_products route 接管的单位产品导入",
                )
            ],
            risk_level="medium",
            metadata={
                "source": "legacy_excel_route",
                "route": "/api/ai/sqlite/import_unit_products",
                "artifacts": [
                    {
                        "artifact_type": "database_file",
                        "name": saved_name,
                        "source": "legacy_excel_route",
                        "summary": f"unit_products_db 导入源文件，目标客户：{unit_name}",
                        "fields": [
                            {"name": "saved_name", "value": saved_name},
                            {"name": "unit_name", "value": unit_name},
                        ],
                    }
                ],
            },
        )
        run = AgentOrchestrator().start_run_from_plan(
            user_id=str(data.get("user_id") or data.get("userId") or "legacy-excel-route"),
            message=str(data.get("message") or f"导入 {saved_name} 到 {unit_name}"),
            plan=plan,
            runtime_context={
                "route": "/api/ai/sqlite/import_unit_products",
                "source": "legacy_excel_route",
                "saved_name": saved_name,
                "unit_name": unit_name,
            },
            auto_execute=True,
        )
        return JSONResponse(
            {
                "success": True,
                "message": "已创建导入任务，等待用户确认"
                if run.status == "waiting_user"
                else "导入任务已处理",
                "run_id": run.run_id,
                "agent_run_id": run.run_id,
                "data": run.to_dict(),
            },
            status_code=202 if run.status in {"waiting_user", "blocked"} else 200,
        )
    except RECOVERABLE_ERRORS as e:
        return JSONResponse({"success": False, "message": f"导入失败：{str(e)}"}, status_code=500)


@router.post("/api/skills/analyze/excel")
def skills_analyze_excel(request: Request, body: dict = Body(default_factory=dict)):
    data = body or {}
    if not data:
        return JSONResponse({"success": False, "message": "请求数据不能为空"}, status_code=400)
    file_path = data.get("file_path")
    if not file_path:
        return JSONResponse({"success": False, "message": "缺少参数: file_path"}, status_code=400)
    payload = _run_excel_skill_agent(
        request=request,
        body=data,
        route_path="/api/skills/analyze/excel",
        tool_id="excel_analyzer",
        action="analyze",
        params={
            "file_path": file_path,
            "sheet_name": data.get("sheet_name"),
            "output_json": data.get("output_json"),
        },
        intent="skills_analyze_excel",
        message=f"Analyze Excel skill file: {file_path}",
    )
    return JSONResponse(payload, status_code=200)


@router.post("/api/skills/view/excel")
def skills_view_excel(request: Request, body: dict = Body(default_factory=dict)):
    data = body or {}
    if not data:
        return JSONResponse({"success": False, "message": "请求数据不能为空"}, status_code=400)
    file_path = data.get("file_path")
    if not file_path:
        return JSONResponse({"success": False, "message": "缺少参数：file_path"}, status_code=400)
    action = str(data.get("action") or "view").strip().lower() or "view"
    payload = _run_excel_skill_agent(
        request=request,
        body=data,
        route_path="/api/skills/view/excel",
        tool_id="excel_toolkit",
        action=action,
        params={
            "file_path": file_path,
            "sheet_name": data.get("sheet_name"),
            "max_rows": data.get("max_rows"),
        },
        intent=f"skills_view_excel_{action}",
        message=f"View Excel skill file: {file_path}",
    )
    return JSONResponse(payload, status_code=200)


@router.post("/api/skills/generate-label-template")
def skills_generate_label_template(request: Request, body: dict = Body(default_factory=dict)):
    data = body or {}
    if not data:
        return JSONResponse({"success": False, "message": "请求数据不能为空"}, status_code=400)
    image_path = data.get("image_path")
    if not image_path:
        return JSONResponse({"success": False, "message": "缺少参数：image_path"}, status_code=400)
    payload = _run_excel_skill_agent(
        request=request,
        body=data,
        route_path="/api/skills/generate-label-template",
        tool_id="label_template_generator",
        action="execute",
        params={
            "image_path": image_path,
            "class_name": data.get("class_name", "LabelTemplateGenerator"),
            "output_file": data.get("output_file"),
            "enable_ocr": data.get("enable_ocr", True),
            "verbose": data.get("verbose", True),
        },
        intent="skills_generate_label_template",
        message="Generate label template from image: " + str(image_path),
    )
    return JSONResponse(payload, status_code=200)
