"""Excel 向量索引 API（自归档 excel_vector 蓝图迁移）。"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from app.application import get_excel_vector_ingest_app_service, get_excel_vector_search_app_service
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_utils import get_upload_dir

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/excel/vector", tags=["excel-vector"])

__all__ = [
    "get_excel_vector_ingest_app_service",
    "get_excel_vector_search_app_service",
    "router",
]


def _excel_vector_user_id(request: Request | None) -> str:
    if request is None:
        return "excel-vector-route"
    return str(
        request.headers.get("X-User-Id")
        or request.headers.get("X-User-ID")
        or request.headers.get("X-Workspace-Id")
        or "excel-vector-route"
    ).strip()


def _run_excel_vector_agent(
    *,
    request: Request | None,
    action: str,
    node_id: str,
    message: str,
    params: dict[str, Any],
) -> Any:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode

    plan = PlanGraph(
        plan_id=f"excel_vector_{action}",
        intent=f"excel_vector_{action}",
        todo_steps=["通过 AgentOrchestrator 执行 Excel 向量工具"],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id="excel_vector_index",
                action=action,
                params=dict(params or {}),
                risk="low",
                idempotent=True,
                description="Execute Excel vector indexing/query through the unified Agent runtime.",
            )
        ],
        risk_level="low",
        metadata={
            "source": "excel_vector_route",
            "route": "/api/excel/vector",
        },
    )
    return AgentOrchestrator().start_run_from_plan(
        user_id=_excel_vector_user_id(request),
        message=message,
        plan=plan,
        runtime_context={
            "source": "excel_vector_route",
            "route_action": action,
            "request_path": str(getattr(getattr(request, "url", None), "path", "") or ""),
        },
    )


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


def _excel_vector_status(payload: dict[str, Any]) -> int:
    if payload.get("success"):
        return 200
    if str(payload.get("error_code") or "") == "excel_vector_exception":
        return 500
    return 400


@router.post("/ingest")
async def ingest_excel_vector(request: Request):
    try:
        payload: dict[str, Any] = {}
        file_path: str = ""
        should_cleanup = False

        ct = (request.headers.get("content-type") or "").lower()
        if "multipart/form-data" in ct:
            form = await request.form()
            upload = form.get("excel_file")
            if upload is not None and hasattr(upload, "filename") and upload.filename:
                if not str(upload.filename).lower().endswith((".xlsx", ".xls")):
                    return JSONResponse(
                        {"success": False, "message": "只支持 .xlsx/.xls 文件"}, status_code=400
                    )
                filename = f"vector_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{upload.filename}"
                file_path = os.path.join(get_upload_dir(), filename)
                body = await upload.read()
                with open(file_path, "wb") as f:
                    f.write(body)
                should_cleanup = True
                payload = {
                    k: v for k, v in form.items() if k != "excel_file" and isinstance(v, str)
                }
            else:
                return JSONResponse(
                    {"success": False, "message": "请选择 Excel 文件"}, status_code=400
                )
        else:
            try:
                payload = await request.json()
            except RECOVERABLE_ERRORS:
                payload = {}
            file_path = str(payload.get("file_path") or "").strip()
            if not file_path:
                return JSONResponse(
                    {"success": False, "message": "请提供 file_path 或上传 excel_file"},
                    status_code=400,
                )

        index_name = str(payload.get("index_name") or "").strip() or None
        index_id = str(payload.get("index_id") or "").strip() or None

        run = _run_excel_vector_agent(
            request=request,
            action="execute",
            node_id="excel_vector_ingest",
            message=f"Excel vector ingest: {index_name or index_id or file_path}",
            params={
                "file_path": file_path,
                "index_name": index_name or "",
                "index_id": index_id or "",
            },
        )
        result = _agent_node_output(run, "excel_vector_ingest")
        if should_cleanup and os.path.exists(file_path):
            os.remove(file_path)
        status = _excel_vector_status(result)
        return JSONResponse(result, status_code=status)
    except RECOVERABLE_ERRORS as err:
        logger.exception("Excel 向量化 ingest 失败: %s", err)
        return JSONResponse({"success": False, "message": str(err)}, status_code=500)


@router.post("/query")
def query_excel_vector(request: Request, data: dict[str, Any] = Body(default_factory=dict)):
    try:
        index_id = str(data.get("index_id") or "").strip()
        query_text = str(data.get("query") or "").strip()
        top_k = int(data.get("top_k", 5))
        run = _run_excel_vector_agent(
            request=request,
            action="query",
            node_id="excel_vector_query",
            message=f"Excel vector query: {query_text}",
            params={"index_id": index_id, "query": query_text, "top_k": top_k},
        )
        result = _agent_node_output(run, "excel_vector_query")
        status = _excel_vector_status(result)
        return JSONResponse(result, status_code=status)
    except RECOVERABLE_ERRORS as err:
        logger.exception("Excel 向量 query 失败: %s", err)
        return JSONResponse({"success": False, "message": str(err)}, status_code=500)


@router.get("/indexes")
def list_excel_vector_indexes():
    try:
        search_service = get_excel_vector_search_app_service()
        return JSONResponse(search_service.list_indexes())
    except RECOVERABLE_ERRORS as err:
        logger.exception("获取向量索引失败: %s", err)
        return JSONResponse({"success": False, "message": str(err)}, status_code=500)


@router.delete("/indexes/{index_id}")
def delete_excel_vector_index(index_id: str):
    try:
        search_service = get_excel_vector_search_app_service()
        result = search_service.delete_index(index_id=index_id)
        status = 200 if result.get("success") else 404
        return JSONResponse(result, status_code=status)
    except RECOVERABLE_ERRORS as err:
        logger.exception("删除向量索引失败: %s", err)
        return JSONResponse({"success": False, "message": str(err)}, status_code=500)
