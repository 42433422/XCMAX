"""Migrated from legacy_products.py (v10)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, File, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["legacy-products"], deprecated=True)


def _svc():
    from app.bootstrap import get_products_service

    return get_products_service()


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


def _products_agent_user_id(request: Request, payload: dict[str, Any]) -> str:
    return str(
        request.headers.get("X-User-Id")
        or request.headers.get("X-User-ID")
        or payload.get("user_id")
        or payload.get("userId")
        or "products-route"
    ).strip()


def _run_products_agent(
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
    action_meta = dict((registry.get("products") or {}).get("actions") or {}).get(action)
    if not isinstance(action_meta, dict):
        return {
            "success": False,
            "message": f"未注册的 products 动作: {action}",
            "agent_status": "failed",
        }

    node_id = f"products_{action}"
    user_id = _products_agent_user_id(request, params)
    plan = PlanGraph(
        plan_id=node_id,
        intent=node_id,
        todo_steps=[f"通过 AgentOrchestrator 执行 products.{action}"],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id="products",
                action=action,
                params=dict(params or {}),
                risk=str(action_meta.get("risk") or "medium"),
                idempotent=bool(action_meta.get("idempotent", False)),
                description=f"Execute products.{action} through the unified Agent runtime.",
            )
        ],
        risk_level=str(action_meta.get("risk") or "medium"),
        metadata={"source": "product_route", "route": route_path},
    )
    runtime_context = {
        "source": "product_route",
        "route": route_path,
        "request_path": str(request.url.path),
        "user_id": user_id,
        "route_confirmed": True,
        "service_source": "fastapi_product_route",
    }
    orchestrator = AgentOrchestrator()
    run = orchestrator.start_run_from_plan(
        user_id=user_id,
        message=str(params.get("message") or f"Products {action}"),
        plan=plan,
        runtime_context=runtime_context,
    )
    if run.status == "waiting_user":
        continued = orchestrator.continue_run(
            run.run_id,
            approved_by=user_id or "products-route",
            runtime_context=runtime_context,
        )
        if continued is not None:
            run = continued
    return _agent_node_output(run, node_id)


@router.delete("/api/products/{product_id}")
def products_delete(request: Request, product_id: int):
    return _run_products_agent(
        request=request,
        action="delete",
        params={"id": product_id},
        route_path="/api/products/{product_id}",
    )


@router.post("/api/products/import/price-list-template")
async def products_import_price_list_template(
    template_file: UploadFile | None = File(default=None),
):
    try:
        from app.infrastructure.documents.template_registry import fhd_repo_root
    except RECOVERABLE_ERRORS as e:
        logger.exception("template_registry import failed")
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)

    if template_file is None or not template_file.filename:
        return JSONResponse({"success": False, "message": "请上传 .docx 模板文件"}, status_code=400)
    if not str(template_file.filename).lower().endswith(".docx"):
        return JSONResponse({"success": False, "message": "只支持 .docx 格式"}, status_code=400)
    try:
        body = await template_file.read()
    except RECOVERABLE_ERRORS as e:
        logger.exception("price list template read failed")
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)
    if len(body) < 64:
        return JSONResponse({"success": False, "message": "文件过小或已损坏"}, status_code=400)
    if not body.startswith(b"PK"):
        return JSONResponse(
            {"success": False, "message": "不是有效的 Office Open XML（.docx）文件"},
            status_code=400,
        )
    try:
        dest_dir = fhd_repo_root() / "424" / "document_templates"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "price_list_default.docx"
        dest.write_bytes(body)
        rel = dest.relative_to(fhd_repo_root())
    except RECOVERABLE_ERRORS as e:
        logger.exception("price list template write failed")
        return JSONResponse({"success": False, "message": f"保存失败：{e}"}, status_code=500)
    return {
        "success": True,
        "message": f"已保存价目表 Word 模板（{rel.as_posix()}），导出 Word 价目表时将使用该文件。",
    }


@router.get("/api/products/export.xlsx")
def products_export_xlsx(
    unit: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    template_id: str | None = Query(default=None),
):
    import os as _os

    service = _svc()
    result = service.export_to_excel(unit_name=unit, keyword=keyword, template_id=template_id)
    if not result.get("success"):
        return JSONResponse(result, status_code=400)
    file_path = result.get("file_path")
    filename = result.get("filename")
    if file_path and _os.path.exists(file_path):
        return FileResponse(
            file_path,
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    return JSONResponse({"success": False, "message": "导出文件不存在"}, status_code=500)


@router.get("/api/products/product_names")
def products_product_names():
    return _svc().get_product_names()


@router.get("/api/products/product_names/search")
def products_product_names_search(keyword: str = Query(default="")):
    return _svc().get_product_names(keyword=keyword)


@router.get("/api/products/search")
def products_search(keyword: str = Query(default="")):
    return _svc().get_products(keyword=keyword)


@router.post("/api/products/batch")
def products_batch(request: Request, body: dict = Body(default_factory=dict)):
    data = body or {}
    products = data.get("products") or []
    if not isinstance(products, list) or not products:
        return JSONResponse(
            {"success": False, "message": "products 必须为非空数组"}, status_code=400
        )
    return _run_products_agent(
        request=request,
        action="batch_create",
        params={"products": products},
        route_path="/api/products/batch",
    )


@router.post("/api/products/{product_id}")
def products_update_post(
    request: Request,
    product_id: int,
    body: dict = Body(default_factory=dict),
):
    result = _run_products_agent(
        request=request,
        action="update",
        params={"id": product_id, **dict(body or {})},
        route_path="/api/products/{product_id}",
    )
    return JSONResponse(result, status_code=200 if result.get("success") else 400)


@router.put("/api/products/{product_id}")
def products_put(request: Request, product_id: int, body: dict = Body(default_factory=dict)):
    result = _run_products_agent(
        request=request,
        action="update",
        params={"id": product_id, **dict(body or {})},
        route_path="/api/products/{product_id}",
    )
    return JSONResponse(result, status_code=200 if result.get("success") else 400)


@router.patch("/api/products/{product_id}")
def products_patch(request: Request, product_id: int, body: dict = Body(default_factory=dict)):
    result = _run_products_agent(
        request=request,
        action="update",
        params={"id": product_id, **dict(body or {})},
        route_path="/api/products/{product_id}",
    )
    return JSONResponse(result, status_code=200 if result.get("success") else 400)
