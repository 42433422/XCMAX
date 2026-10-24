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
    # Failed dry-runs still carry private paths in message/errors; only success
    # previews may pass through unchanged.
    if result.get("success"):
        return result
    requested_code = str(result.get("error_code") or "").strip()
    error_code = requested_code if requested_code in _PUBLIC_ETL_ERRORS else "operation_failed"
    payload: dict[str, Any] = {
        "success": False,
        "message": _PUBLIC_ETL_ERRORS.get(error_code, fallback),
        "error_code": error_code,
    }
    for key in (
        "dry_run",
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



# --- inlined from excel_extract_shipment_part01 ---
def _facade():
    return importlib.import_module("app.fastapi_routes.domains.excel.excel_extract_shipment")


def _adapters():
    return _facade()._build_etl_http()


@_facade().router.post(
    "/shipment-etl/preview",
    dependencies=[_facade().Depends(_facade().require_legacy_shipment_etl_access)],
)
async def shipment_etl_preview(
    file: _facade().UploadFile | None = _facade().File(default=None),
    file_path: str = _facade().Form(""),
    workspace_root: str = _facade().Form(""),
    include_ledger: str = _facade().Form("auto"),
    save_as_template: str = _facade().Form("0"),
    template_name: str = _facade().Form(""),
    template_scope: str = _facade().Form(""),
):
    from app.fastapi_routes.shipment_etl.ports import TemplateCapture

    imports, *_rest = _adapters()
    return await imports.preview(
        file,
        file_path,
        str(workspace_root or "").strip() or None,
        _facade()._form_include_ledger(include_ledger),
        TemplateCapture(
            enabled=_facade()._form_truthy(save_as_template, False),
            name=str(template_name or "").strip(),
            scope=str(template_scope or "").strip(),
        ),
    )


@_facade().router.post(
    "/shipment-etl/execute",
    dependencies=[_facade().Depends(_facade().require_legacy_shipment_etl_access)],
)
async def shipment_etl_execute(
    file: _facade().UploadFile | None = _facade().File(default=None),
    file_path: str = _facade().Form(""),
    workspace_root: str = _facade().Form(""),
    notes_json: str = _facade().Form(""),
    import_products: str = _facade().Form("1"),
    import_shipments: str = _facade().Form("1"),
    idempotent: str = _facade().Form("1"),
    include_ledger: str = _facade().Form("0"),
    confirm_ledger: str = _facade().Form("0"),
    dry_run: str = _facade().Form("0"),
    direct: str = _facade().Form("0"),
    force_shipment_target: str = _facade().Form("0"),
    save_as_template: str = _facade().Form("0"),
    template_name: str = _facade().Form(""),
    template_scope: str = _facade().Form(""),
    _user: Any = _facade().Depends(_facade().require_identified_user),
):
    from app.fastapi_routes.shipment_etl.ports import TemplateCapture

    imports, *_rest = _adapters()
    return await imports.execute(
        file,
        file_path,
        str(workspace_root or "").strip() or None,
        notes_json,
        import_products=_facade()._form_truthy(import_products, True),
        import_shipments=_facade()._form_truthy(import_shipments, True),
        idempotent=_facade()._form_truthy(idempotent, True),
        include_ledger=_facade()._form_include_ledger(include_ledger, default="0"),
        confirm_ledger=_facade()._form_truthy(confirm_ledger, False),
        dry_run=_facade()._form_truthy(dry_run, False),
        direct=_facade()._form_truthy(direct, False),
        force_shipment_target=_facade()._form_truthy(force_shipment_target, False),
        template=TemplateCapture(
            enabled=_facade()._form_truthy(save_as_template, False),
            name=str(template_name or "").strip(),
            scope=str(template_scope or "").strip(),
        ),
    )


@_facade().router.post(
    "/shipment-etl/ocr-preview",
    dependencies=[_facade().Depends(_facade().require_tenant_etl_preview)],
)
async def shipment_etl_ocr_preview(
    file: _facade().UploadFile | None = _facade().File(default=None),
    file_path: str = _facade().Form(""),
    workspace_root: str = _facade().Form(""),
    include_ledger: str = _facade().Form("auto"),
    _user: Any = _facade().Depends(_facade().require_identified_user),
):
    _imports, ocr, *_rest = _adapters()
    return await ocr.run(
        file,
        file_path,
        str(workspace_root or "").strip() or None,
        _facade()._form_include_ledger(include_ledger),
    )


@_facade().router.post(
    "/shipment-etl/batch-preview",
    dependencies=[_facade().Depends(_facade().require_legacy_shipment_etl_access)],
)
async def shipment_etl_batch_preview(
    directory: str = _facade().Form(""),
    workspace_root: str = _facade().Form(""),
    include_ledger: str = _facade().Form("auto"),
    _user: Any = _facade().Depends(_facade().require_identified_user),
):
    imports, *_rest = _adapters()
    return imports.batch_preview(
        directory,
        str(workspace_root or "").strip() or None,
        _facade()._form_include_ledger(include_ledger),
    )


@_facade().router.post(
    "/shipment-etl/batch-execute",
    dependencies=[_facade().Depends(_facade().require_legacy_shipment_etl_access)],
)
async def shipment_etl_batch_execute(
    directory: str = _facade().Form(""),
    workspace_root: str = _facade().Form(""),
    include_ledger: str = _facade().Form("0"),
    confirm_ledger: str = _facade().Form("0"),
    idempotent: str = _facade().Form("1"),
    import_products: str = _facade().Form("1"),
    import_shipments: str = _facade().Form("1"),
    dry_run: str = _facade().Form("0"),
    _user: Any = _facade().Depends(_facade().require_identified_user),
):
    imports, *_rest = _adapters()
    return imports.batch_execute(
        directory,
        str(workspace_root or "").strip() or None,
        include_ledger=_facade()._form_include_ledger(include_ledger, default="0"),
        confirm_ledger=_facade()._form_truthy(confirm_ledger, False),
        idempotent=_facade()._form_truthy(idempotent, True),
        import_products=_facade()._form_truthy(import_products, True),
        import_shipments=_facade()._form_truthy(import_shipments, True),
        dry_run=_facade()._form_truthy(dry_run, False),
    )

# --- inlined from excel_extract_shipment_part02 ---
def _facade():
    return importlib.import_module("app.fastapi_routes.domains.excel.excel_extract_shipment")


def _adapters():
    return _facade()._build_etl_http()


@_facade().router.post(
    "/shipment-etl/generate-template",
    dependencies=[_facade().Depends(_facade().require_legacy_shipment_etl_access)],
)
async def shipment_etl_generate_template(
    kind: str = _facade().Form("delivery"),
    output_path: str = _facade().Form(""),
    unit_name: str = _facade().Form("闭环测试客户"),
    _user: Any = _facade().Depends(_facade().require_identified_user),
):
    _i, _o, _h, templates = _adapters()
    return templates.generate(kind, output_path, unit_name)


@_facade().router.post(
    "/shipment-etl/regenerate",
    dependencies=[_facade().Depends(_facade().require_legacy_shipment_etl_access)],
)
async def shipment_etl_regenerate(
    file_path: str = _facade().Form(""),
    output_path: str = _facade().Form(""),
    workspace_root: str = _facade().Form(""),
    include_ledger: str = _facade().Form("auto"),
    _user: Any = _facade().Depends(_facade().require_identified_user),
):
    _i, _o, _h, templates = _adapters()
    return templates.regenerate(
        file_path,
        output_path,
        str(workspace_root or "").strip() or None,
        _facade()._form_include_ledger(include_ledger),
    )


@_facade().router.get("/logs")
def get_extract_logs(
    data_type: str | None = _facade().Query(default=None),
    status: str | None = _facade().Query(default=None),
    limit: int = _facade().Query(default=50),
    offset: int = _facade().Query(default=0),
):
    _i, _o, history, _t = _adapters()
    return history.list(data_type, status, limit, offset)


@_facade().router.get("/logs/{log_id}")
def get_extract_log(log_id: int):
    _i, _o, history, _t = _adapters()
    return history.detail(log_id)


@_facade().router.get("/preview/{log_id}")
def get_preview(log_id: int):
    _i, _o, history, _t = _adapters()
    return history.detail(log_id, preview=True)
