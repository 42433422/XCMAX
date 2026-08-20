# ruff: noqa: F401, I001
"""Shipment ETL and extraction-log routes for Excel data."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from app.fastapi_routes.excel_extract import (
    TEMP_EXCEL_DIR,
    _form_include_ledger,
    _form_truthy,
    logger,
    router,
)
from app.infrastructure.auth.dependencies import require_identified_user
from app.utils.operational_errors import RECOVERABLE_ERRORS

_PUBLIC_ETL_ERRORS = {
    "unsafe_path": "非法文件路径",
    "missing_path": "缺少文件路径",
    "missing_file": "文件不存在",
    "not_ocr_source": "不支持的 OCR 文件类型",
    "ocr_empty": "OCR 未识别到有效内容",
    "ocr_grid_empty": "OCR 内容无法识别为表格",
    "ocr_failed": "OCR 处理失败，请稍后重试",
    "ledger_confirm_required": "检测到出货流水，请确认客户归属后再入库",
    "direct_execute_denied": "无预览直写未开启",
    "batch_disabled": "批量入库功能未开启",
    "batch_too_large": "批量文件过多，请缩小范围",
    "no_delivery_notes": "没有可导入的单据",
    "unsupported_profile_target": "识别到不支持直接入库的模板",
    "product_import_failed": "客户或产品导入失败，已中止发货单写入",
}


def _safe_failed_etl_result(result: dict[str, Any], fallback: str) -> dict[str, Any]:
    """Keep operational failure metadata without exposing internal exception text."""
    if result.get("success") or result.get("dry_run"):
        return result
    requested_code = str(result.get("error_code") or "").strip()
    error_code = requested_code if requested_code in _PUBLIC_ETL_ERRORS else "operation_failed"
    payload: dict[str, Any] = {
        "success": False,
        "message": _PUBLIC_ETL_ERRORS.get(error_code, fallback),
        "error_code": error_code,
    }
    for key in (
        "note_count",
        "ledger_note_count",
        "shipment_created",
        "shipment_failed",
        "shipment_skipped",
        "would_create",
        "would_skip",
        "safe_to_retry",
        "closed_loop",
    ):
        value = result.get(key)
        if isinstance(value, (bool, int)):
            payload[key] = value
    return payload


def _temporary_upload_path(prefix: str, original_name: str, allowed_suffixes: set[str]) -> str:
    suffix = Path(original_name).suffix.lower()
    if suffix not in allowed_suffixes:
        suffix = next(iter(sorted(allowed_suffixes)))
    return str(Path(TEMP_EXCEL_DIR) / f"{prefix}_{uuid4().hex}{suffix}")


from app.fastapi_routes.excel_extract_shipment_part01 import (
    shipment_etl_batch_execute as shipment_etl_batch_execute,
)
from app.fastapi_routes.excel_extract_shipment_part01 import (
    shipment_etl_batch_preview as shipment_etl_batch_preview,
)
from app.fastapi_routes.excel_extract_shipment_part01 import (
    shipment_etl_execute as shipment_etl_execute,
)
from app.fastapi_routes.excel_extract_shipment_part01 import (
    shipment_etl_ocr_preview as shipment_etl_ocr_preview,
)
from app.fastapi_routes.excel_extract_shipment_part01 import (
    shipment_etl_preview as shipment_etl_preview,
)
from app.fastapi_routes.excel_extract_shipment_part02 import (
    get_extract_log as get_extract_log,
)
from app.fastapi_routes.excel_extract_shipment_part02 import (
    get_extract_logs as get_extract_logs,
)
from app.fastapi_routes.excel_extract_shipment_part02 import (
    get_preview as get_preview,
)
from app.fastapi_routes.excel_extract_shipment_part02 import (
    shipment_etl_generate_template as shipment_etl_generate_template,
)
from app.fastapi_routes.excel_extract_shipment_part02 import (
    shipment_etl_regenerate as shipment_etl_regenerate,
)
