"""Product price documents and export template previews."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from .export_flow import ProductExports


class ProductExportRoutes:
    """Product price documents and export template previews."""

    def __init__(self, *, exports: Callable[[], ProductExports]) -> None:
        router = self.router = APIRouter()

        @router.get("/products/price-list-export")
        @router.get("/products/price-list-export/", include_in_schema=False)
        def products_price_list_export(
            request: Request,
            unit: str | None = Query(None),
            keyword: str | None = Query(None),
            export_date: str | None = Query(None, description="报价日期 YYYY-MM-DD，默认当天"),
            template_id: str | None = Query(
                None, description="模板 slug（GET /api/document-templates?role=price_list_docx）"
            ),
        ) -> Response:
            return exports().document(request, unit, keyword, export_date, template_id)

        self.products_price_list_export = products_price_list_export

        @router.get("/products/export.docx")
        @router.get("/products/export.docx/", include_in_schema=False)
        def products_export_docx(
            request: Request,
            unit: str | None = Query(None),
            keyword: str | None = Query(None),
            export_date: str | None = Query(None, description="报价日期 YYYY-MM-DD，默认当天"),
            template_id: str | None = Query(
                None, description="模板 slug（GET /api/document-templates?role=price_list_docx）"
            ),
        ) -> Response:
            return exports().document(request, unit, keyword, export_date, template_id)

        self.products_export_docx = products_export_docx

        @router.get("/products/price-list-template-preview")
        @router.get("/products/price-list-template-preview/", include_in_schema=False)
        def products_price_list_template_preview(
            request: Request,
            template_id: str | None = Query(
                None, description="模板 slug（与 price-list-export 一致）"
            ),
        ) -> dict:
            return exports().preview(request, template_id)

        self.products_price_list_template_preview = products_price_list_template_preview
