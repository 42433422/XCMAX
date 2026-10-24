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

from app.fastapi_routes.domains.excel.excel_extract import (
    TEMP_EXCEL_DIR,
    _form_include_ledger,
    _form_truthy,
    logger,
    router,
)
from app.infrastructure.auth.dependencies import require_identified_user
from app.infrastructure.auth.shipment_etl_access_gate import (
    require_legacy_shipment_etl_access,
    require_tenant_etl_preview,
)
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



def _build_etl_http():
    """Compose shipment_etl HTTP adapters (upload ownership + public errors)."""
    from datetime import datetime as _dt

    from app.application.office_template_ingest_app_service import (
        attach_template_ingest_to_etl_result,
    )
    from app.application.shipment_excel_etl_app_service import (
        get_shipment_excel_etl_app_service,
        preview_shipment_excel_etl,
    )
    from app.application.shipment_excel_etl_ocr import parse_ocr_document
    from app.application.shipment_excel_etl_security import (
        resolve_etl_output_path,
        resolve_etl_path,
    )
    from app.bootstrap import get_extract_log_service
    from app.fastapi_routes.shipment_etl.history import HistoryViews
    from app.fastapi_routes.shipment_etl.imports import ShipmentImports
    from app.fastapi_routes.shipment_etl.ocr import OcrPreview
    from app.fastapi_routes.shipment_etl.responses import EtlResponses
    from app.fastapi_routes.shipment_etl.templates import TemplateOutputs
    from app.fastapi_routes.shipment_etl.uploads import UploadStager

    responses = EtlResponses(sanitize=_safe_failed_etl_result, logger=logger)
    uploads = UploadStager(_temporary_upload_path, logger)
    imports = ShipmentImports(
        get_shipment_excel_etl_app_service,
        attach_template_ingest_to_etl_result,
        uploads,
        responses,
    )
    ocr = OcrPreview(parse_ocr_document, preview_shipment_excel_etl, uploads, responses)
    history = HistoryViews(get_extract_log_service, responses)
    templates = TemplateOutputs(
        get_shipment_excel_etl_app_service,
        resolve_etl_path,
        resolve_etl_output_path,
        lambda: TEMP_EXCEL_DIR,
        _dt.now,
        responses,
    )
    return imports, ocr, history, templates



from app.fastapi_routes.domains.excel.excel_extract_shipment_part01 import (
    shipment_etl_batch_execute as shipment_etl_batch_execute,
)
from app.fastapi_routes.domains.excel.excel_extract_shipment_part01 import (
    shipment_etl_batch_preview as shipment_etl_batch_preview,
)
from app.fastapi_routes.domains.excel.excel_extract_shipment_part01 import (
    shipment_etl_execute as shipment_etl_execute,
)
from app.fastapi_routes.domains.excel.excel_extract_shipment_part01 import (
    shipment_etl_ocr_preview as shipment_etl_ocr_preview,
)
from app.fastapi_routes.domains.excel.excel_extract_shipment_part01 import (
    shipment_etl_preview as shipment_etl_preview,
)
from app.fastapi_routes.domains.excel.excel_extract_shipment_part02 import (
    get_extract_log as get_extract_log,
)
from app.fastapi_routes.domains.excel.excel_extract_shipment_part02 import (
    get_extract_logs as get_extract_logs,
)
from app.fastapi_routes.domains.excel.excel_extract_shipment_part02 import (
    get_preview as get_preview,
)
from app.fastapi_routes.domains.excel.excel_extract_shipment_part02 import (
    shipment_etl_generate_template as shipment_etl_generate_template,
)
from app.fastapi_routes.domains.excel.excel_extract_shipment_part02 import (
    shipment_etl_regenerate as shipment_etl_regenerate,
)
