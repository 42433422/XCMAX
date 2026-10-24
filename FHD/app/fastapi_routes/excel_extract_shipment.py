<<<<<<< HEAD
"""Shipment ETL HTTP contracts composed from explicit application adapters."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse

from app.fastapi_routes.excel_extract import (
    TEMP_EXCEL_DIR,
    _form_include_ledger,
    _form_truthy,
    logger,
    router,
)
from app.fastapi_routes.shipment_etl.history import HistoryViews
from app.fastapi_routes.shipment_etl.imports import ShipmentImports
from app.fastapi_routes.shipment_etl.ocr import OcrPreview
from app.fastapi_routes.shipment_etl.ports import (
    ExtractionHistory,
    Payload,
    ShipmentApplication,
    TemplateCapture,
)
from app.fastapi_routes.shipment_etl.responses import (
    PUBLIC_ETL_ERRORS as _PUBLIC_ETL_ERRORS,
)
from app.fastapi_routes.shipment_etl.responses import EtlResponses, safe_failed_result
from app.fastapi_routes.shipment_etl.templates import TemplateOutputs
from app.fastapi_routes.shipment_etl.uploads import UploadStager
from app.infrastructure.auth.dependencies import require_identified_user
from app.infrastructure.auth.shipment_etl_access_gate import (
    require_legacy_shipment_etl_access,
    require_tenant_etl_preview,
)


def _safe_failed_etl_result(result: dict[str, Any], fallback: str) -> dict[str, Any]:
    return safe_failed_result(result, fallback, errors=_PUBLIC_ETL_ERRORS)


def _temporary_upload_path(prefix: str, original_name: str, allowed_suffixes: set[str]) -> str:
    suffix = Path(original_name).suffix.lower()
    if suffix not in allowed_suffixes:
        suffix = next(iter(sorted(allowed_suffixes)))
    return str(Path(TEMP_EXCEL_DIR) / f"{prefix}_{uuid4().hex}{suffix}")


def _service() -> ShipmentApplication:
    from app.application.shipment_excel_etl_app_service import get_shipment_excel_etl_app_service

    return get_shipment_excel_etl_app_service()


def _capture(
    result: Payload,
    *,
    file_path: str | Path | None,
    save_as_template: bool,
    template_name: str,
    template_scope: str,
    source: str,
) -> Payload:
    from app.application.office_template_ingest_app_service import (
        attach_template_ingest_to_etl_result,
    )

    return attach_template_ingest_to_etl_result(
        result,
        file_path=file_path,
        save_as_template=save_as_template,
        template_name=template_name,
        template_scope=template_scope,
        source=source,
    )


def _document_preview(
    file_path: str | Path, *, include_ledger: bool | str, workspace_root: str | None
) -> Payload:
    from app.application.shipment_excel_etl_app_service import preview_shipment_excel_etl

    return preview_shipment_excel_etl(
        file_path, include_ledger=include_ledger, workspace_root=workspace_root
    )


def _ocr_parse(
    file_path: str | Path, *, include_ledger: bool | str, workspace_root: str | None
) -> Payload:
    from app.application.shipment_excel_etl_ocr import parse_ocr_document

    return parse_ocr_document(
        file_path, include_ledger=include_ledger, workspace_root=workspace_root
    )


def _responses() -> EtlResponses:
    return EtlResponses(_safe_failed_etl_result, logger)


def _imports() -> ShipmentImports:
    return ShipmentImports(
        _service, _capture, UploadStager(_temporary_upload_path, logger), _responses()
    )


def _templates() -> TemplateOutputs:
    from app.application.shipment_excel_etl_security import (
        resolve_etl_output_path,
        resolve_etl_path,
    )

    return TemplateOutputs(
        _service,
        resolve_etl_path,
        resolve_etl_output_path,
        lambda: TEMP_EXCEL_DIR,
        datetime.now,
        _responses(),
    )


def _history_service() -> ExtractionHistory:
    from app.bootstrap import get_extract_log_service

    return get_extract_log_service()


def _history() -> HistoryViews:
    return HistoryViews(_history_service, _responses())


def _template_capture(save: str, name: str, scope: str) -> TemplateCapture:
    return TemplateCapture(
        _form_truthy(save, False), str(name or "").strip(), str(scope or "").strip()
    )


@router.post(
    "/shipment-etl/preview",
    dependencies=[Depends(require_legacy_shipment_etl_access)],
)
async def shipment_etl_preview(
    file: UploadFile | None = File(default=None),
    file_path: str = Form(""),
    workspace_root: str = Form(""),
    include_ledger: str = Form("auto"),
    save_as_template: str = Form("0"),
    template_name: str = Form(""),
    template_scope: str = Form(""),
) -> JSONResponse:
    """预览：按内容指纹识别送货单/出货流水并抽取抬头+明细（不写业务库）。

    ``save_as_template=1`` 时额外把源办公文件解析入库模版库。
    """
    return await _imports().preview(
        file,
        file_path,
        str(workspace_root or "").strip() or None,
        _form_include_ledger(include_ledger),
        _template_capture(save_as_template, template_name, template_scope),
    )


@router.post(
    "/shipment-etl/execute",
    dependencies=[Depends(require_legacy_shipment_etl_access)],
)
async def shipment_etl_execute(
    file: UploadFile | None = File(default=None),
    file_path: str = Form(""),
    workspace_root: str = Form(""),
    notes_json: str = Form(""),
    import_products: str = Form("1"),
    import_shipments: str = Form("1"),
    idempotent: str = Form("1"),
    include_ledger: str = Form("0"),
    confirm_ledger: str = Form("0"),
    dry_run: str = Form("0"),
    direct: str = Form("0"),
    force_shipment_target: str = Form("0"),
    save_as_template: str = Form("0"),
    template_name: str = Form(""),
    template_scope: str = Form(""),
    _user: Any = Depends(require_identified_user),
) -> JSONResponse:
    """执行闭环：单据 → 客户/产品/发货单（默认幂等；流水需 confirm_ledger）。

    direct=1：无预览直写（需环境开关 FHD_EXCEL_ETL_ALLOW_DIRECT=1）。
    save_as_template=1：额外把源办公文件解析入库模版库。
    """
    return await _imports().execute(
        file,
        file_path,
        str(workspace_root or "").strip() or None,
        notes_json,
        import_products=_form_truthy(import_products, True),
        import_shipments=_form_truthy(import_shipments, True),
        idempotent=_form_truthy(idempotent, True),
        include_ledger=_form_include_ledger(include_ledger, default="0"),
        confirm_ledger=_form_truthy(confirm_ledger, False),
        dry_run=_form_truthy(dry_run, False),
        direct=_form_truthy(direct, False),
        force_shipment_target=_form_truthy(force_shipment_target, False),
        template=_template_capture(save_as_template, template_name, template_scope),
    )


@router.post(
    "/shipment-etl/ocr-preview",
    dependencies=[Depends(require_tenant_etl_preview)],
)
async def shipment_etl_ocr_preview(
    file: UploadFile | None = File(default=None),
    file_path: str = Form(""),
    workspace_root: str = Form(""),
    include_ledger: str = Form("auto"),
    _user: Any = Depends(require_identified_user),
) -> JSONResponse:
    """扫描件/图片/PDF OCR → 表格 → 单据预览。"""
    return await OcrPreview(
        _ocr_parse, _document_preview, UploadStager(_temporary_upload_path, logger), _responses()
    ).run(
        file,
        file_path,
        str(workspace_root or "").strip() or None,
        _form_include_ledger(include_ledger, default="auto"),
    )


@router.post(
    "/shipment-etl/batch-preview",
    dependencies=[Depends(require_legacy_shipment_etl_access)],
)
async def shipment_etl_batch_preview(
    directory: str = Form(""),
    workspace_root: str = Form(""),
    include_ledger: str = Form("auto"),
    _user: Any = Depends(require_identified_user),
) -> JSONResponse:
    """批量预览目录内 xlsx 送货单/出货流水。"""
    return _imports().batch_preview(
        directory, str(workspace_root or "").strip() or None, _form_include_ledger(include_ledger)
    )


@router.post(
    "/shipment-etl/batch-execute",
    dependencies=[Depends(require_legacy_shipment_etl_access)],
)
async def shipment_etl_batch_execute(
    directory: str = Form(""),
    workspace_root: str = Form(""),
    include_ledger: str = Form("0"),
    confirm_ledger: str = Form("0"),
    idempotent: str = Form("1"),
    import_products: str = Form("1"),
    import_shipments: str = Form("1"),
    dry_run: str = Form("0"),
    _user: Any = Depends(require_identified_user),
) -> JSONResponse:
    """批量执行目录内 xlsx 闭环入库（默认关闭，需 FHD_SHIPMENT_ETL_ALLOW_BATCH=1）。"""
    return _imports().batch_execute(
        directory,
        str(workspace_root or "").strip() or None,
        include_ledger=_form_include_ledger(include_ledger, default="0"),
        confirm_ledger=_form_truthy(confirm_ledger, False),
        idempotent=_form_truthy(idempotent, True),
        import_products=_form_truthy(import_products, True),
        import_shipments=_form_truthy(import_shipments, True),
        dry_run=_form_truthy(dry_run, False),
    )


@router.post(
    "/shipment-etl/generate-template",
    dependencies=[Depends(require_legacy_shipment_etl_access)],
)
async def shipment_etl_generate_template(
    kind: str = Form("delivery"),
    output_path: str = Form(""),
    unit_name: str = Form("闭环测试客户"),
    _user: Any = Depends(require_identified_user),
) -> JSONResponse:
    """生成测试用送货单或出货流水模板（输出限沙箱）。"""
    return _templates().generate(kind, output_path, unit_name)


@router.post(
    "/shipment-etl/regenerate",
    dependencies=[Depends(require_legacy_shipment_etl_access)],
)
async def shipment_etl_regenerate(
    file_path: str = Form(""),
    output_path: str = Form(""),
    workspace_root: str = Form(""),
    include_ledger: str = Form("auto"),
    _user: Any = Depends(require_identified_user),
) -> JSONResponse:
    """解析已有单据并按标准送货单版式反推再出单。"""
    return _templates().regenerate(
        file_path,
        output_path,
        str(workspace_root or "").strip() or None,
        _form_include_ledger(include_ledger),
    )


@router.get("/logs")
def get_extract_logs(
    data_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50),
    offset: int = Query(default=0),
) -> JSONResponse:
    return _history().list(data_type, status, limit, offset)


@router.get("/logs/{log_id}")
def get_extract_log(log_id: int) -> JSONResponse:
    return _history().detail(log_id)


@router.get("/preview/{log_id}")
def get_preview(log_id: int) -> JSONResponse:
    return _history().detail(log_id, preview=True)
=======
"""兼容入口：canonical 位于 domains.excel.excel_extract_shipment。"""

from __future__ import annotations

import sys

from app.fastapi_routes.domains.excel import excel_extract_shipment as _canonical

sys.modules[__name__] = _canonical
>>>>>>> origin/main
