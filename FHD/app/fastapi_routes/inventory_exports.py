"""Tenant-scoped inventory download routes shared by Excel and CSV exports."""

from __future__ import annotations

import logging
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
router = APIRouter(tags=["inventory"])


def _svc():
    from app.application.inventory_app_service import InventoryAppService

    return InventoryAppService()


@router.get(
    "/api/inventory/export.xlsx",
    response_class=Response,
    summary="Export the complete filtered inventory workbook",
    description="Returns a tenant-scoped Excel snapshot; empty or over-limit results are rejected.",
    responses={
        200: {
            "content": {
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {
                    "schema": {"type": "string", "format": "binary"}
                }
            }
        },
        404: {"description": "No inventory matches the filters"},
        413: {"description": "More than 50,000 rows; narrow the filters"},
        500: {"description": "Workbook generation failed"},
    },
)
def inventory_export(
    warehouse_id: int | None = Query(default=None, ge=1),
    product_id: int | None = Query(default=None, ge=1),
    batch_no: str | None = Query(default=None, max_length=50),
    keyword: str | None = Query(default=None, max_length=200),
):
    return _inventory_export_response("xlsx", warehouse_id, product_id, batch_no, keyword)


@router.get(
    "/api/inventory/export.csv",
    response_class=Response,
    summary="Export complete filtered inventory as UTF-8 BOM CSV",
    responses={
        200: {"content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}}},
        404: {"description": "No inventory matches the filters"},
        413: {"description": "More than 50,000 rows; narrow the filters"},
        500: {"description": "CSV generation failed"},
    },
)
def inventory_export_csv(
    warehouse_id: int | None = Query(default=None, ge=1),
    product_id: int | None = Query(default=None, ge=1),
    batch_no: str | None = Query(default=None, max_length=50),
    keyword: str | None = Query(default=None, max_length=200),
):
    return _inventory_export_response("csv", warehouse_id, product_id, batch_no, keyword)


def _inventory_export_response(output_format, warehouse_id, product_id, batch_no, keyword):
    try:
        result = _svc().export_inventory(
            output_format=output_format,
            warehouse_id=warehouse_id,
            product_id=product_id,
            batch_no=batch_no,
            keyword=keyword,
        )
        if not result.get("success"):
            status = 413 if result.get("error_code") == "INVENTORY_EXPORT_LIMIT" else 404
            return JSONResponse(result, status_code=status, headers={"Cache-Control": "no-store"})
        filename = f"库存明细-{datetime.now():%Y%m%d-%H%M%S}.{output_format}"
        return Response(
            result["content"],
            media_type=(
                "text/csv"
                if output_format == "csv"
                else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            headers={
                "Content-Disposition": f"attachment; filename=inventory.{output_format}; filename*=UTF-8''{quote(filename)}",
                "X-Inventory-Row-Count": str(result["total"]),
                "Cache-Control": "no-store",
            },
        )
    except RECOVERABLE_ERRORS:
        logger.exception("Inventory export failed")
        return JSONResponse(
            {
                "success": False,
                "error_code": "INVENTORY_EXPORT_FAILED",
                "message": "库存导出失败，请稍后重试。",
            },
            status_code=500,
            headers={"Cache-Control": "no-store"},
        )
