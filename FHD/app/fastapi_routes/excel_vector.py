"""Excel 向量索引 API（自归档 excel_vector 蓝图迁移）。"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, cast

from fastapi import APIRouter, Body, Request, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.application import get_excel_vector_ingest_app_service, get_excel_vector_search_app_service
from app.fastapi_routes.domains.agent.route_support import request_runtime_context
from app.fastapi_routes.tools_execute import run_tools_execute_agent
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.upload_helpers import save_upload_bytes

logger = logging.getLogger(__name__)
_EXCEL_VECTOR_UNAVAILABLE = "Excel 向量服务暂时不可用，请稍后重试"

router = APIRouter(prefix="/api/excel/vector", tags=["excel-vector"])

__all__ = [
    "get_excel_vector_ingest_app_service",
    "get_excel_vector_search_app_service",
    "router",
]


def _run_excel_vector_agent(
    *,
    request: Request,
    action: str,
    params: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    return run_tools_execute_agent(
        request=request,
        body={"tool_id": "excel_vector_index", "action": action, "params": params},
        route_path=str(request.url.path),
    )


@router.post("/ingest")
async def ingest_excel_vector(request: Request):
    upload_file: UploadFile | None = None
    file_path = ""
    context = request_runtime_context(request)
    try:
        payload: dict[str, Any] = {}

        ct = (request.headers.get("content-type") or "").lower()
        if "multipart/form-data" in ct:
            form = await request.form()
            upload = form.get("excel_file")
            if upload is not None and hasattr(upload, "filename") and upload.filename:
                upload_file = cast("UploadFile", upload)
                if not str(upload_file.filename).lower().endswith((".xlsx", ".xls")):
                    return JSONResponse(
                        {"success": False, "message": "只支持 .xlsx/.xls 文件"}, status_code=400
                    )
                suffix = ".xls" if str(upload_file.filename).lower().endswith(".xls") else ".xlsx"
                body = await upload_file.read()
                scope = ":".join(
                    str(context.get(key) or "") for key in ("user_id", "tenant_id", "mod_id")
                )
                owner = hashlib.sha256(scope.encode()).hexdigest()
                # Content identity is stable across network retries; retained inputs
                # remain available while the canonical task is awaiting approval.
                filename = hashlib.sha256(body).hexdigest() + suffix
                file_path = await run_in_threadpool(
                    save_upload_bytes, body, subdir=f"excel-vector/{owner}", filename=filename
                )
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

        result, status = await run_in_threadpool(
            _run_excel_vector_agent,
            request=request,
            action="execute",
            params={
                "file_path": file_path,
                "index_name": index_name or "",
                "index_id": index_id or "",
            },
        )
        return JSONResponse(result, status_code=status)
    except RECOVERABLE_ERRORS:
        logger.exception("Excel 向量化 ingest 失败")
        return JSONResponse(
            {"success": False, "message": "Excel 向量化服务暂时不可用，请稍后重试"},
            status_code=500,
        )
    finally:
        if upload_file is not None:
            try:
                await upload_file.close()
            except RECOVERABLE_ERRORS:
                logger.warning("关闭 Excel 向量上传文件失败", exc_info=True)


@router.post("/query")
def query_excel_vector(request: Request, data: dict[str, Any] = Body(default_factory=dict)):
    try:
        index_id = str(data.get("index_id") or "").strip()
        query_text = str(data.get("query") or "").strip()
        top_k = int(data.get("top_k", 5))
        result, status = _run_excel_vector_agent(
            request=request,
            action="query",
            params={"index_id": index_id, "query": query_text, "top_k": top_k},
        )
        return JSONResponse(result, status_code=status)
    except RECOVERABLE_ERRORS:
        logger.exception("Excel 向量 query 失败")
        return JSONResponse(
            {"success": False, "message": _EXCEL_VECTOR_UNAVAILABLE}, status_code=500
        )


@router.get("/indexes")
def list_excel_vector_indexes(request: Request):
    result, status = _run_excel_vector_agent(request=request, action="list", params={})
    return JSONResponse(result, status_code=status)


@router.delete("/indexes/{index_id}")
def delete_excel_vector_index(request: Request, index_id: str):
    result, status = _run_excel_vector_agent(
        request=request, action="delete", params={"index_id": index_id}
    )
    return JSONResponse(result, status_code=status)
