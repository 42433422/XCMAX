"""Mutation and document-export operations behind product compatibility routes."""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, cast
from urllib.parse import quote

from fastapi import HTTPException
from fastapi.responses import Response


def execute_product_action(
    action: str,
    data: dict[str, Any],
    *,
    parse_id: Callable[[Any], int | None],
    parse_quantity: Callable[..., Any],
    parse_is_active: Callable[..., Any],
    insert_row: Callable[..., Any],
    update_row: Callable[..., Any],
    delete_row: Callable[..., Any],
    batch_delete_rows: Callable[..., Any],
    http_exception_result: Callable[[HTTPException], dict[str, Any]],
    recoverable_errors: tuple[type[BaseException], ...],
    logger: Any,
) -> dict[str, Any]:
    """Execute one compatibility mutation with explicitly injected persistence ports."""
    try:
        from app.mod_sdk.erp_products_facade import (
            is_erp_products_via_service_enabled,
        )
        from app.mod_sdk.erp_products_facade import (
            products_add as add_via_service,
        )
        from app.mod_sdk.erp_products_facade import (
            products_batch_delete as batch_delete_via_service,
        )
        from app.mod_sdk.erp_products_facade import (
            products_delete as delete_via_service,
        )
        from app.mod_sdk.erp_products_facade import (
            products_update as update_via_service,
        )

        if is_erp_products_via_service_enabled():
            service_actions = {
                "create": add_via_service,
                "update": update_via_service,
                "delete": delete_via_service,
                "batch_delete": batch_delete_via_service,
            }
            if action in service_actions:
                return cast("dict[str, Any]", service_actions[action](None, data))
    except HTTPException as exc:
        return http_exception_result(exc)
    except recoverable_errors:
        logger.debug("products compat via service skipped", exc_info=True)

    if action == "create":
        from app.application.excel_imports import _parse_price

        try:
            new_id = insert_row(
                data,
                parse_price=_parse_price,
                parse_quantity=parse_quantity,
                parse_is_active=parse_is_active,
            )
            return {"success": True, "data": {"id": new_id}}
        except HTTPException as exc:
            return http_exception_result(exc)
        except recoverable_errors as exc:
            logger.exception("products add failed")
            return {"success": False, "message": f"添加失败：{exc}", "error_code": "tool_exception"}

    if action == "update":
        from app.application.excel_imports import _parse_price

        product_id = parse_id(data.get("id"))
        if product_id is None:
            return {"success": False, "message": "id 无效或缺失", "status_code": 400}
        try:
            update_row(
                product_id,
                data,
                parse_price=_parse_price,
                parse_quantity=parse_quantity,
                parse_is_active=parse_is_active,
            )
            return {"success": True, "data": {"id": product_id}}
        except HTTPException as exc:
            return http_exception_result(exc)
        except recoverable_errors as exc:
            logger.exception("products update failed")
            return {"success": False, "message": f"更新失败：{exc}", "error_code": "tool_exception"}

    if action == "delete":
        product_id = parse_id(data.get("id"))
        if product_id is None:
            return {"success": False, "message": "id 无效或缺失", "status_code": 400}
        try:
            delete_row(product_id)
            return {"success": True, "message": "已删除"}
        except HTTPException as exc:
            return http_exception_result(exc)
        except recoverable_errors as exc:
            logger.exception("products delete failed")
            return {"success": False, "message": f"删除失败：{exc}", "error_code": "tool_exception"}

    if action == "batch_delete":
        ids = data.get("ids") or data.get("product_ids") or []
        if not isinstance(ids, list) or not ids:
            return {"success": False, "message": "ids 须为非空数组", "status_code": 400}
        try:
            deleted, skipped = batch_delete_rows(ids)
            skipped_items = (
                skipped if isinstance(skipped, list) else ([] if not skipped else [skipped])
            )
            return {
                "success": True,
                "message": f"已删除 {deleted} 条",
                "deleted": deleted,
                "skipped": skipped_items,
            }
        except recoverable_errors as exc:
            logger.exception("products batch-delete failed")
            return {
                "success": False,
                "message": f"批量删除失败：{exc}",
                "error_code": "tool_exception",
            }

    return {"success": False, "message": f"未注册的 products compat 动作: {action}"}


def price_list_word_response(
    unit: str | None,
    keyword: str | None,
    export_date: str | None,
    template_slug: str | None,
    *,
    load_products: Callable[[str | None, str | None], list[dict[str, Any]]],
    recoverable_errors: tuple[type[BaseException], ...],
    logger: Any,
) -> Response:
    """Build the product price-list document returned by both export aliases."""
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
    template_path, template_relative = resolve_price_list_docx_template(template_slug)
    if not template_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=(
                "未找到 Word 模板文件："
                f"{template_relative}。请将 .docx 放到 424/document_templates/（如 price_list_default.docx），"
                "或在「模板预览」中登记，或设置环境变量 FHD_PRICE_LIST_DOCX_TEMPLATE。"
            ),
        )
    rows = load_products(keyword, unit)
    customer = (unit or "").strip()
    quote_date = (export_date or "").strip() or date.today().strftime("%Y-%m-%d")
    try:
        body = build_price_list_docx_bytes(
            template_path,
            customer_name=customer,
            quote_date=quote_date,
            products=rows,
        )
    except recoverable_errors as exc:
        logger.exception("products export docx failed")
        raise HTTPException(status_code=500, detail=f"生成 Word 失败：{exc}") from exc

    today = date.today().strftime("%Y-%m-%d")
    filename = f"产品价格表_{customer or '全部单位'}_{today}.docx"
    disposition = "attachment; filename=\"price-list.docx\"; filename*=UTF-8''" + quote(
        filename, safe=""
    )
    return Response(
        content=body,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": disposition},
    )
