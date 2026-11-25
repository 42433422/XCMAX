"""Document-export operations behind product compatibility routes."""

from __future__ import annotations

from datetime import date
from typing import Any, Callable
from urllib.parse import quote

from fastapi import HTTPException
from fastapi.responses import Response


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
    builtin = not template_path.is_file() and template_slug in (None, "", "price_list_default")
    if not template_path.is_file() and not builtin:
        raise HTTPException(
            status_code=404,
            detail=(
                "未找到 Word 模板文件："
                f"{template_relative}。请将 .docx 放到 424/document_templates/（如 price_list_default.docx），"
                "或在「模板预览」中登记，或设置环境变量 FHD_PRICE_LIST_DOCX_TEMPLATE。"
            ),
        )
    customer = (unit or "").strip()
    quote_date = (export_date or "").strip() or date.today().strftime("%Y-%m-%d")
    try:
        rows = load_products(keyword, unit)
        body = build_price_list_docx_bytes(
            None if builtin else template_path,
            builtin_default=builtin,
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
