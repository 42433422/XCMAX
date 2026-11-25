"""Migrated from legacy_products.py (v10)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, File, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.fastapi_routes.tools_execute import _capability_http_receipt
from app.infrastructure.auth.business_scope_gate import require_scoped_business_permission
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.security.safe_download_path import (
    UnsafeDownloadPathError,
    resolve_under_allowed_dirs,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["legacy-products"],
    deprecated=True,
    dependencies=[Depends(require_scoped_business_permission("product.view", "product.edit"))],
)


def _svc():
    from app.bootstrap import get_products_service

    return get_products_service()


def _products_agent_user_id(request: Request, payload: dict[str, Any]) -> str:
    from app.fastapi_routes.tools_execute import user_id_from_tool_request

    return user_id_from_tool_request(request, payload)


def _run_products_agent(
    *, request: Request, action: str, params: dict[str, Any], route_path: str
) -> dict[str, Any]:
    from app.fastapi_routes.tools_execute import run_tools_execute_agent

    payload, _ = run_tools_execute_agent(
        request=request,
        body={"tool_id": "products", "action": action, "params": dict(params)},
        route_path=route_path,
    )
    return payload


@router.delete("/api/products/{product_id}")
def products_delete(request: Request, product_id: int):
    result = _run_products_agent(
        request=request,
        action="delete",
        params={"id": product_id},
        route_path="/api/products/{product_id}",
    )
    return JSONResponse(*_capability_http_receipt(result))


@router.post("/api/products/import/price-list-template")
async def products_import_price_list_template(
    request: Request,
    template_file: UploadFile | None = File(default=None),
):
    from app.fastapi_routes.domains.agent.route_support import request_runtime_context
    from app.utils.path_io.upload_helpers import stage_capability_upload

    context = request_runtime_context(request)

    if template_file is None or not template_file.filename:
        return JSONResponse({"success": False, "message": "请上传 .docx 模板文件"}, status_code=400)
    if not str(template_file.filename).lower().endswith(".docx"):
        return JSONResponse({"success": False, "message": "只支持 .docx 格式"}, status_code=400)
    try:
        body = await template_file.read(8 * 1024 * 1024 + 1)
    except RECOVERABLE_ERRORS:
        logger.exception("price list template read failed")
        return JSONResponse({"success": False, "message": "模板文件读取失败"}, status_code=500)
    if len(body) < 64:
        return JSONResponse({"success": False, "message": "文件过小或已损坏"}, status_code=400)
    if len(body) > 8 * 1024 * 1024:
        return JSONResponse({"success": False, "message": "模板文件不能超过 8 MB"}, status_code=413)
    if not body.startswith(b"PK"):
        return JSONResponse(
            {"success": False, "message": "不是有效的 Office Open XML（.docx）文件"},
            status_code=400,
        )
    try:
        params = stage_capability_upload(
            body,
            template_file.filename,
            context,
            namespace="price-list-template",
            suffixes=frozenset({".docx"}),
        )
    except RECOVERABLE_ERRORS:
        logger.exception("price list template staging failed")
        return JSONResponse({"success": False, "message": "模板输入保存失败"}, status_code=500)
    result = _run_products_agent(
        request=request,
        action="import_price_list_template",
        params=params,
        route_path="/api/products/import/price-list-template",
    )
    return JSONResponse(*_capability_http_receipt(result))


@router.get("/api/products/export.xlsx")
def products_export_xlsx(
    request: Request,
    unit: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    template_id: str | None = Query(default=None),
):
    from app.infrastructure.auth.db_token import verify_db_read_token_header

    verify_db_read_token_header(request)
    service = _svc()
    result = service.export_to_excel(unit_name=unit, keyword=keyword, template_id=template_id)
    if not result.get("success"):
        return JSONResponse(result, status_code=400)
    file_path = result.get("file_path")
    filename = result.get("filename")
    from app.utils.path_io.path_utils import get_data_dir

    try:
        safe_file_path = resolve_under_allowed_dirs(str(file_path or ""), [Path(get_data_dir())])
    except UnsafeDownloadPathError:
        return JSONResponse({"success": False, "message": "导出文件路径无效"}, status_code=500)
    if safe_file_path.is_file():  # lgtm[py/path-injection] -- resolved under application data
        return FileResponse(
            safe_file_path,
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
    result = _run_products_agent(
        request=request,
        action="batch_create",
        params={"products": products},
        route_path="/api/products/batch",
    )
    return JSONResponse(*_capability_http_receipt(result))


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
    return JSONResponse(*_capability_http_receipt(result))


@router.put("/api/products/{product_id}")
def products_put(request: Request, product_id: int, body: dict = Body(default_factory=dict)):
    result = _run_products_agent(
        request=request,
        action="update",
        params={"id": product_id, **dict(body or {})},
        route_path="/api/products/{product_id}",
    )
    return JSONResponse(*_capability_http_receipt(result))


@router.patch("/api/products/{product_id}")
def products_patch(request: Request, product_id: int, body: dict = Body(default_factory=dict)):
    result = _run_products_agent(
        request=request,
        action="update",
        params={"id": product_id, **dict(body or {})},
        route_path="/api/products/{product_id}",
    )
    return JSONResponse(*_capability_http_receipt(result))
