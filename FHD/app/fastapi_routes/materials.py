"""原材料 API（继承自归档 materials 蓝图的端点契约）。"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from app.application import get_material_application_service
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["materials"])


def _svc():
    return get_material_application_service()


def _agent_node_output(run: Any, node_id: str) -> dict[str, Any]:
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
    return output


def _materials_agent_user_id(request: Request, payload: dict[str, Any]) -> str:
    return str(
        request.headers.get("X-User-Id")
        or request.headers.get("X-User-ID")
        or payload.get("user_id")
        or payload.get("userId")
        or "materials-route"
    ).strip()


def _run_materials_agent(
    *,
    request: Request,
    action: str,
    params: dict[str, Any],
    route_path: str,
) -> dict[str, Any]:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode
    from app.services.tools_execution.registry import get_workflow_tool_registry

    registry = get_workflow_tool_registry()
    action_meta = dict((registry.get("materials") or {}).get("actions") or {}).get(action)
    if not isinstance(action_meta, dict):
        return {
            "success": False,
            "message": f"未注册的 materials 动作: {action}",
            "agent_status": "failed",
        }

    node_id = f"materials_{action}"
    user_id = _materials_agent_user_id(request, params)
    plan = PlanGraph(
        plan_id=node_id,
        intent=node_id,
        todo_steps=[f"通过 AgentOrchestrator 执行 materials.{action}"],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id="materials",
                action=action,
                params=dict(params or {}),
                risk=str(action_meta.get("risk") or "medium"),
                idempotent=bool(action_meta.get("idempotent", False)),
                description=f"Execute materials.{action} through the unified Agent runtime.",
            )
        ],
        risk_level=str(action_meta.get("risk") or "medium"),
        metadata={"source": "materials_route", "route": route_path},
    )
    runtime_context = {
        "source": "materials_route",
        "route": route_path,
        "request_path": str(request.url.path),
        "user_id": user_id,
        "route_confirmed": True,
        "service_source": "fastapi_materials_route",
    }
    orchestrator = AgentOrchestrator()
    run = orchestrator.start_run_from_plan(
        user_id=user_id,
        message=str(params.get("message") or f"Materials {action}"),
        plan=plan,
        runtime_context=runtime_context,
    )
    if run.status == "waiting_user":
        continued = orchestrator.continue_run(
            run.run_id,
            approved_by=user_id or "materials-route",
            runtime_context=runtime_context,
        )
        if continued is not None:
            run = continued
    return _agent_node_output(run, node_id)


@router.post("/api/materials")
def add_material(request: Request, data: dict[str, Any] = Body(default_factory=dict)):
    try:
        if "name" not in data:
            return JSONResponse(
                {"success": False, "message": "原材料名称不能为空"}, status_code=400
            )

        name = data.get("name")
        if isinstance(name, str):
            if name == "":
                return JSONResponse(
                    {"success": False, "message": "原材料名称不能为空"}, status_code=400
                )
            name_str = name
        else:
            name_str = str(name)
        if not name_str.strip():
            name_str = "未命名原材料"

        material_code = data.get("material_code")
        if not isinstance(material_code, str) or not material_code.strip():
            material_code = f"M-{uuid.uuid4().hex[:10]}"

        data["material_code"] = material_code
        data["name"] = name_str.strip() if isinstance(name_str, str) else str(name_str)

        if "min_stock" not in data and "min_quantity" in data:
            data["min_stock"] = data.get("min_quantity")

        result = _run_materials_agent(
            request=request,
            action="create",
            params=data,
            route_path="/api/materials",
        )
        status = 200 if result.get("success") else 400
        if result.get("error_code") == "tool_exception":
            status = 500
        return JSONResponse(result, status_code=status)
    except RECOVERABLE_ERRORS as e:
        logger.error("添加原材料失败：%s", e)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.get("/api/materials")
def get_materials(
    search: str = "",
    category: str = "",
    page: int | None = Query(default=None),
    per_page: int | None = Query(default=None),
):
    try:
        page_v = page if isinstance(page, int) and page > 0 else 1
        per_v = per_page if isinstance(per_page, int) and per_page > 0 else 20
        result = _svc().get_all_materials(
            search=search,
            category=category if category else None,
            page=page_v,
            per_page=per_v,
        )
        if result.get("success") and "count" not in result:
            result["count"] = len(result.get("data") or [])
        return JSONResponse(result, status_code=200)
    except RECOVERABLE_ERRORS as e:
        logger.error("获取原材料列表失败：%s", e)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.put("/api/materials/{material_id}")
def update_material(
    request: Request,
    material_id: int,
    data: dict[str, Any] = Body(default_factory=dict),
):
    try:
        params = {"id": material_id, **dict(data or {})}
        result = _run_materials_agent(
            request=request,
            action="update",
            params=params,
            route_path="/api/materials/{material_id}",
        )
        if not result.get("success"):
            status = 500 if result.get("error_code") == "tool_exception" else 400
            return JSONResponse(result, status_code=status)
        payload = result.get("data") or {}
        if isinstance(payload, dict):
            payload.setdefault("id", material_id)
            for k, v in (data or {}).items():
                if v is not None:
                    payload[k] = v
        result["message"] = result.get("message") or "更新成功"
        result["data"] = payload
        return JSONResponse(
            result,
            status_code=200,
        )
    except RECOVERABLE_ERRORS as e:
        logger.error("更新原材料失败：%s", e)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.delete("/api/materials/{material_id}")
def delete_material(request: Request, material_id: int):
    try:
        result = _run_materials_agent(
            request=request,
            action="delete",
            params={"id": material_id},
            route_path="/api/materials/{material_id}",
        )
        if not result.get("success"):
            status = 500 if result.get("error_code") == "tool_exception" else 400
            return JSONResponse(result, status_code=status)
        result["message"] = result.get("message") or "删除成功"
        return JSONResponse(result, status_code=200)
    except RECOVERABLE_ERRORS as e:
        logger.error("删除原材料失败：%s", e)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.post("/api/materials/batch-delete")
def batch_delete_materials(
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
):
    try:
        if not isinstance(data, dict):
            return JSONResponse(
                {"success": False, "message": "请求体必须是 JSON 对象"}, status_code=400
            )

        ids = data.get("material_ids")
        if ids is None:
            ids = data.get("ids", [])

        valid_ids: list[int] = []
        for raw_id in ids or []:
            try:
                valid_ids.append(int(raw_id))
            except (TypeError, ValueError):
                continue

        deleted_count = len(valid_ids)
        result = _run_materials_agent(
            request=request,
            action="batch_delete",
            params={"ids": valid_ids},
            route_path="/api/materials/batch-delete",
        )
        if not result.get("success"):
            if result.get("error_code") == "tool_exception":
                logger.error("批量删除原材料时 Agent 执行异常：%s", result.get("message"))
            else:
                return JSONResponse(result, status_code=400)
        return JSONResponse(
            {
                **result,
                "success": True,
                "message": f"已删除 {deleted_count} 条记录",
                "deleted_count": deleted_count,
            },
            status_code=200,
        )
    except RECOVERABLE_ERRORS as e:
        logger.error("批量删除原材料失败：%s", e)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.get("/api/materials/low-stock")
def get_low_stock_materials(threshold: float | None = Query(default=None)):
    try:
        result = _svc().get_low_stock_materials(threshold=threshold)
        return JSONResponse(result, status_code=200)
    except RECOVERABLE_ERRORS as e:
        logger.error("获取低库存原材料失败：%s", e)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.get("/api/materials/export")
def export_materials(
    search: str | None = Query(default=None),
    category: str | None = Query(default=None),
    template_id: str | None = Query(default=None),
):
    try:
        result = _svc().export_to_excel(search=search, category=category, template_id=template_id)
        if not result.get("success"):
            return JSONResponse(result, status_code=400)
        file_path = result.get("file_path")
        if file_path and os.path.exists(str(file_path)):
            return FileResponse(
                str(file_path),
                filename=result.get("filename", "原材料导出.xlsx"),
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        return JSONResponse({"success": False, "message": "导出文件不存在"}, status_code=500)
    except RECOVERABLE_ERRORS as e:
        logger.error("导出原材料失败：%s", e)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)
