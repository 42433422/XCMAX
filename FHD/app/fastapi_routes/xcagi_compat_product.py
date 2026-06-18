"""
XCAGI 前端兼容 API — 产品 / 库存 / 报价表导出路由。
"""

from __future__ import annotations

import logging
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from app.infrastructure.auth.db_token import verify_db_read_token_header
from app.infrastructure.persistence.compat_db.base import (
    _business_mod_json_block,
    _product_parse_id,
    _product_parse_is_active,
    _product_parse_quantity,
    _products_write_raise,
)
from app.infrastructure.persistence.compat_db.product_queries import (
    _load_products_all_for_export,
    _load_products_list_impl_pg,
)
from app.infrastructure.persistence.compat_db.queries import (
    _merged_purchase_unit_entries,
    _products_units_for_select,
)
from app.infrastructure.persistence.compat_db.writes import (
    products_pg_batch_delete_rows,
    products_pg_delete_row,
    products_pg_insert_row,
    products_pg_update_row,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

router = APIRouter(tags=["xcagi-compat"])
logger = logging.getLogger(__name__)


def _products_price_list_word_response(
    unit: str | None,
    keyword: str | None,
    export_date: str | None,
    template_slug: str | None = None,
) -> Response:
    from app.infrastructure.documents.price_list_export import (
        build_price_list_docx_bytes,
        resolve_price_list_docx_template,
    )
    from app.shell.mod_business_scope import business_data_exposed, business_data_hidden_reason

    if not business_data_exposed():
        raise HTTPException(
            status_code=503,
            detail=business_data_hidden_reason() or "扩展 Mod 未就绪，无法导出价格表。",
        )
    tpl_path, tpl_rel = resolve_price_list_docx_template(template_slug)
    if not tpl_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=(
                "未找到 Word 模板文件："
                f"{tpl_rel}。请将 .docx 放到 424/document_templates/（如 price_list_default.docx），"
                "或在「模板预览」中登记，或设置环境变量 FHD_PRICE_LIST_DOCX_TEMPLATE。"
            ),
        )
    rows = _load_products_all_for_export(keyword, unit)
    customer = (unit or "").strip()
    qd = (export_date or "").strip() or date.today().strftime("%Y-%m-%d")
    try:
        body = build_price_list_docx_bytes(
            tpl_path,
            customer_name=customer,
            quote_date=qd,
            products=rows,
        )
    except RECOVERABLE_ERRORS as e:
        logger.exception("products export docx failed")
        raise HTTPException(status_code=500, detail=f"生成 Word 失败：{e}") from e

    today = date.today().strftime("%Y-%m-%d")
    label = customer or "全部单位"
    utf8_name = f"产品价格表_{label}_{today}.docx"
    disp = "attachment; filename=\"price-list.docx\"; filename*=UTF-8''" + quote(utf8_name, safe="")
    return Response(
        content=body,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": disp},
    )


@router.get("/products/units")
def products_units(request: Request) -> dict:
    verify_db_read_token_header(request)
    return _products_units_for_select()


@router.get("/shipment/shipment-records/units")
@router.get("/shipment/shipment-records/units/")
def shipment_records_units() -> dict:
    return _products_units_for_select()


@router.get("/purchase_units")
@router.get("/purchase_units/")
def purchase_units_list() -> dict:
    return {"success": True, "data": _merged_purchase_unit_entries()}


@router.get("/products/list")
def products_list(
    request: Request,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=2000),
    keyword: str | None = Query(None),
    unit: str | None = Query(None),
) -> dict:
    try:
        from app.mod_sdk.erp_domain_dispatch import try_invoke_erp_domain_handler

        mod_out = try_invoke_erp_domain_handler(
            "products",
            "list",
            request=request,
            page=page,
            per_page=per_page,
            keyword=keyword,
            unit=unit,
        )
        if mod_out is not None:
            return mod_out
    except RECOVERABLE_ERRORS:
        logger.debug("erp domain products.list dispatch skipped", exc_info=True)
    try:
        from app.mod_sdk.erp_products_facade import (
            is_erp_products_via_service_enabled,
        )
        from app.mod_sdk.erp_products_facade import products_list as products_list_via_service

        if is_erp_products_via_service_enabled():
            return products_list_via_service(
                request, page=page, per_page=per_page, keyword=keyword, unit=unit
            )
    except RECOVERABLE_ERRORS:
        logger.debug("products list via service skipped", exc_info=True)
    verify_db_read_token_header(request)
    try:
        items, total, schema_hint = _load_products_list_impl_pg(page, per_page, keyword, unit)
        out: dict = {"success": True, "data": items, "total": total}
        if schema_hint:
            out["schema_hint"] = schema_hint
        return out
    except RECOVERABLE_ERRORS as e:
        logger.exception("products list failed (postgresql)")
        return {"success": False, "message": str(e), "data": [], "total": 0}


@router.get("/products/{product_id:int}", response_model=None)
@router.get("/products/{product_id:int}/", response_model=None)
def products_get_by_id(request: Request, product_id: int) -> dict | JSONResponse:
    try:
        from app.mod_sdk.erp_products_facade import (
            is_erp_products_via_service_enabled,
        )
        from app.mod_sdk.erp_products_facade import products_get as products_get_via_service

        if is_erp_products_via_service_enabled():
            return products_get_via_service(request, product_id)
    except RECOVERABLE_ERRORS:
        logger.debug("products get via service skipped", exc_info=True)
    verify_db_read_token_header(request)
    from app.bootstrap import get_products_service

    result = get_products_service().get_product(product_id)
    if result.get("success"):
        return result
    return JSONResponse(result, status_code=404)


@router.post("/products/resolve-name-hints")
@router.post("/products/resolve-name-hints/")
def products_resolve_name_hints(request: Request, body: dict = Body(default_factory=dict)) -> dict:
    verify_db_read_token_header(request)
    raw = body.get("hints") or body.get("names") or []
    if not isinstance(raw, list):
        return {"success": False, "message": "hints 须为字符串数组", "data": []}
    hints = [str(x).strip() for x in raw if str(x).strip()]
    if not hints:
        return {"success": False, "message": "hints 不能为空", "data": []}

    gate = _business_mod_json_block()
    if gate:
        return {**gate, "data": []}

    raise HTTPException(
        status_code=501,
        detail=(
            "products/resolve-name-hints 未启用：product_name_resolve 模块已在清理过程中被移除，"
            "请使用销售合同流程中的 name_hint 解析能力。"
        ),
    )


@router.post("/products/update")
@router.post("/products/update/")
def products_update(request: Request, body: dict = Body(default_factory=dict)) -> dict:
    try:
        from app.mod_sdk.erp_products_facade import (
            is_erp_products_via_service_enabled,
        )
        from app.mod_sdk.erp_products_facade import products_update as products_update_via_service

        if is_erp_products_via_service_enabled():
            return products_update_via_service(request, body)
    except HTTPException:
        raise
    except RECOVERABLE_ERRORS:
        logger.debug("products update via service skipped", exc_info=True)
    _products_write_raise(request)
    gate = _business_mod_json_block()
    if gate:
        return gate

    from app.application.excel_imports import _parse_price

    pid = _product_parse_id(body.get("id"))
    if pid is None:
        raise HTTPException(status_code=400, detail="id 无效或缺失")

    try:
        products_pg_update_row(
            pid,
            body,
            parse_price=_parse_price,
            parse_quantity=_product_parse_quantity,
            parse_is_active=_product_parse_is_active,
        )
    except HTTPException:
        raise
    except RECOVERABLE_ERRORS as e:
        logger.exception("products update failed")
        raise HTTPException(status_code=500, detail=f"更新失败：{e}") from e

    return {"success": True, "data": {"id": pid}}


@router.post("/products/add")
@router.post("/products/add/")
def products_add(request: Request, body: dict = Body(default_factory=dict)) -> dict:
    try:
        from app.mod_sdk.erp_products_facade import (
            is_erp_products_via_service_enabled,
        )
        from app.mod_sdk.erp_products_facade import products_add as products_add_via_service

        if is_erp_products_via_service_enabled():
            return products_add_via_service(request, body)
    except HTTPException:
        raise
    except RECOVERABLE_ERRORS:
        logger.debug("products add via service skipped", exc_info=True)
    _products_write_raise(request)
    gate = _business_mod_json_block()
    if gate:
        return gate

    from app.application.excel_imports import _parse_price

    try:
        new_id = products_pg_insert_row(
            body,
            parse_price=_parse_price,
            parse_quantity=_product_parse_quantity,
            parse_is_active=_product_parse_is_active,
        )
    except HTTPException:
        raise
    except RECOVERABLE_ERRORS as e:
        logger.exception("products add failed")
        raise HTTPException(status_code=500, detail=f"添加失败：{e}") from e

    return {"success": True, "data": {"id": new_id}}


@router.post("/products/delete")
@router.post("/products/delete/")
def products_delete(request: Request, body: dict = Body(default_factory=dict)) -> dict:
    try:
        from app.mod_sdk.erp_products_facade import (
            is_erp_products_via_service_enabled,
        )
        from app.mod_sdk.erp_products_facade import products_delete as products_delete_via_service

        if is_erp_products_via_service_enabled():
            return products_delete_via_service(request, body)
    except HTTPException:
        raise
    except RECOVERABLE_ERRORS:
        logger.debug("products delete via service skipped", exc_info=True)
    _products_write_raise(request)
    gate = _business_mod_json_block()
    if gate:
        return gate

    pid = _product_parse_id(body.get("id"))
    if pid is None:
        raise HTTPException(status_code=400, detail="id 无效或缺失")

    try:
        products_pg_delete_row(pid)
    except HTTPException:
        raise
    except RECOVERABLE_ERRORS as e:
        logger.exception("products delete failed")
        raise HTTPException(status_code=500, detail=f"删除失败：{e}") from e

    return {"success": True, "message": "已删除"}


@router.post("/products/batch-delete")
@router.post("/products/batch-delete/")
def products_batch_delete(request: Request, body: dict = Body(default_factory=dict)) -> dict:
    try:
        from app.mod_sdk.erp_products_facade import (
            is_erp_products_via_service_enabled,
        )
        from app.mod_sdk.erp_products_facade import (
            products_batch_delete as products_batch_delete_via_service,
        )

        if is_erp_products_via_service_enabled():
            return products_batch_delete_via_service(request, body)
    except HTTPException:
        raise
    except RECOVERABLE_ERRORS:
        logger.debug("products batch-delete via service skipped", exc_info=True)
    _products_write_raise(request)
    gate = _business_mod_json_block()
    if gate:
        return gate

    ids = body.get("ids") or body.get("product_ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="ids 须为非空数组")

    try:
        deleted, skipped = products_pg_batch_delete_rows(ids)
    except RECOVERABLE_ERRORS as e:
        logger.exception("products batch-delete failed")
        raise HTTPException(status_code=500, detail=f"批量删除失败：{e}") from e

    return {
        "success": True,
        "message": f"已删除 {deleted} 条",
        "deleted": deleted,
        "skipped": skipped,
    }


@router.get("/products/price-list-export")
@router.get("/products/price-list-export/")
def products_price_list_export(
    request: Request,
    unit: str | None = Query(None),
    keyword: str | None = Query(None),
    export_date: str | None = Query(None, description="报价日期 YYYY-MM-DD，默认当天"),
    template_id: str | None = Query(
        None, description="模板 slug（GET /api/document-templates?role=price_list_docx）"
    ),
) -> Response:
    verify_db_read_token_header(request)
    return _products_price_list_word_response(unit, keyword, export_date, template_id)


@router.get("/products/export.docx")
@router.get("/products/export.docx/")
def products_export_docx(
    request: Request,
    unit: str | None = Query(None),
    keyword: str | None = Query(None),
    export_date: str | None = Query(None, description="报价日期 YYYY-MM-DD，默认当天"),
    template_id: str | None = Query(
        None, description="模板 slug（GET /api/document-templates?role=price_list_docx）"
    ),
) -> Response:
    verify_db_read_token_header(request)
    return _products_price_list_word_response(unit, keyword, export_date, template_id)


@router.get("/products/price-list-template-preview")
@router.get("/products/price-list-template-preview/")
def products_price_list_template_preview(
    request: Request,
    template_id: str | None = Query(None, description="模板 slug（与 price-list-export 一致）"),
) -> dict:
    from app.infrastructure.documents.price_list_export import (
        build_price_list_template_preview_json,
    )

    verify_db_read_token_header(request)
    from app.shell.mod_business_scope import business_data_exposed, business_data_hidden_reason

    if not business_data_exposed():
        raise HTTPException(
            status_code=503,
            detail=business_data_hidden_reason() or "扩展 Mod 未就绪。",
        )
    return build_price_list_template_preview_json(template_id)
