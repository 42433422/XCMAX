"""办公文件解析 → 模版库一键入库。

把 ``analyze``（解析）与 ``create``（写 ``templates`` 表）串成单链路，
供 ``POST /api/templates/upload``、Shipment ETL ``save_as_template``、
以及 ``document_template.ingest`` 工具共用。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_SCOPE_TEMPLATE_TYPES = {
    "orders": "出货明细",
    "shipmentRecords": "出货记录",
    "products": "产品目录",
    "materials": "原材料",
    "customers": "客户",
    "shipmentSummary": "汇总统计",
    "salesReport": "销售报表",
}


def _category_from_filename(filename: str, analyzed_type: str = "") -> str:
    ext = Path(str(filename or "")).suffix.lower()
    raw = str(analyzed_type or "").strip().lower()
    if raw == "word" or ext == ".docx":
        return "word"
    if raw in {"pptx", "ppt"} or ext in {".pptx", ".ppt"}:
        return "pptx"
    if raw == "pdf" or ext == ".pdf":
        return "pdf"
    if raw == "label":
        return "label"
    return "excel"


def _template_type_for_ingest(
    *, template_scope: str, analyzed_type: str, source: str = ""
) -> str:
    scope = str(template_scope or "").strip()
    if scope in _SCOPE_TEMPLATE_TYPES:
        return _SCOPE_TEMPLATE_TYPES[scope]
    kind = str(analyzed_type or "").strip().lower()
    src = str(source or "").strip().lower()
    # Shipment ETL / 打单相关入库：默认标为「发货单」，便于 get_default_for_type
    if "shipment" in src and kind in {"", "excel"}:
        return "发货单"
    if kind == "word":
        return "Word"
    if kind == "label":
        return "Label"
    if kind in {"pptx", "ppt"}:
        return "PPTX"
    if kind == "pdf":
        return "PDF"
    return "Excel"


def _build_create_payload_from_analyze(
    analyzed: dict[str, Any],
    *,
    filename: str,
    template_name: str = "",
    template_scope: str = "",
    source: str = "office_upload",
) -> dict[str, Any]:
    preview = analyzed.get("preview_data") if isinstance(analyzed.get("preview_data"), dict) else {}
    analyzed_type = str(analyzed.get("template_type") or "").strip()
    name = (
        str(template_name or "").strip()
        or str(analyzed.get("template_name") or "").strip()
        or Path(filename or "template").stem
    )
    file_path = str(preview.get("file_path") or preview.get("image_path") or "").strip() or None
    scope = str(template_scope or "").strip()
    return {
        "name": name,
        "template_name": name,
        "template_type": _template_type_for_ingest(
            template_scope=scope, analyzed_type=analyzed_type, source=source
        ),
        "business_scope": scope,
        "fields": analyzed.get("fields") if isinstance(analyzed.get("fields"), list) else [],
        "preview_data": preview,
        "category": _category_from_filename(filename, analyzed_type),
        "source": str(source or "office_upload").strip() or "office_upload",
        "file_path": file_path,
        "original_file_path": file_path,
    }


def ingest_office_bytes_to_template_library(
    *,
    file_body: bytes,
    filename: str,
    template_name: str = "",
    template_scope: str = "",
    source: str = "office_upload",
) -> tuple[dict[str, Any], int]:
    """解析办公文件字节并写入模版库 ``templates`` 表。"""
    from app.fastapi_routes.document_templates_compat import (
        run_archive_template_analyze,
        run_archive_template_create,
    )

    name = str(filename or "").strip() or "upload.bin"
    try:
        analyzed, analyze_code = run_archive_template_analyze(
            file_body=file_body or b"",
            filename=name,
            template_name=str(template_name or "").strip(),
            template_scope=str(template_scope or "").strip(),
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("办公文件解析失败: %s", exc)
        return {"success": False, "message": f"解析失败：{exc}", "ingested": False}, 500

    if not isinstance(analyzed, dict) or not analyzed.get("success"):
        payload = dict(analyzed or {})
        payload.setdefault("success", False)
        payload["ingested"] = False
        return payload, int(analyze_code or 400)

    create_payload = _build_create_payload_from_analyze(
        analyzed,
        filename=name,
        template_name=template_name,
        template_scope=template_scope,
        source=source,
    )
    try:
        created, create_code = run_archive_template_create(create_payload)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("模版库入库失败: %s", exc)
        return {
            "success": False,
            "message": f"解析成功但入库失败：{exc}",
            "ingested": False,
            "analyzed": analyzed,
            "task_id": analyzed.get("task_id"),
        }, 500

    if not isinstance(created, dict) or not created.get("success"):
        return {
            "success": False,
            "message": str((created or {}).get("message") or "模版库入库失败"),
            "ingested": False,
            "analyzed": analyzed,
            "create": created,
            "task_id": analyzed.get("task_id"),
            "missing_terms": (created or {}).get("missing_terms"),
            "business_scope": (created or {}).get("business_scope"),
        }, int(create_code or 400)

    return {
        "success": True,
        "message": "解析并入库模版库成功",
        "ingested": True,
        "template": created.get("template"),
        "analyzed": {
            "task_id": analyzed.get("task_id"),
            "template_name": analyzed.get("template_name"),
            "template_type": analyzed.get("template_type"),
            "fields": analyzed.get("fields") or [],
            "preview_data": analyzed.get("preview_data") or {},
        },
        "task_id": analyzed.get("task_id"),
        "source": create_payload.get("source"),
    }, 200


def ingest_office_path_to_template_library(
    file_path: str | Path,
    *,
    template_name: str = "",
    template_scope: str = "",
    source: str = "office_upload",
) -> tuple[dict[str, Any], int]:
    """从本地路径读取办公文件并入库模版库。"""
    path = Path(str(file_path or "")).expanduser()
    if not path.is_file():
        return {
            "success": False,
            "message": f"文件不存在：{path}",
            "ingested": False,
            "error_code": "missing_file",
        }, 400
    try:
        body = path.read_bytes()
    except OSError as exc:
        return {
            "success": False,
            "message": f"读取文件失败：{exc}",
            "ingested": False,
            "error_code": "read_failed",
        }, 400
    return ingest_office_bytes_to_template_library(
        file_body=body,
        filename=path.name,
        template_name=template_name or path.stem,
        template_scope=template_scope,
        source=source,
    )


def attach_template_ingest_to_etl_result(
    result: dict[str, Any],
    *,
    file_path: str | Path | None,
    save_as_template: bool,
    template_name: str = "",
    template_scope: str = "",
    source: str = "shipment_excel_etl",
) -> dict[str, Any]:
    """ETL 成功后可选写入模版库；失败不覆盖业务 ETL 主结果。"""
    out = dict(result or {})
    if not save_as_template:
        return out
    if not out.get("success"):
        out["template_ingest"] = {
            "success": False,
            "ingested": False,
            "message": "ETL 未成功，跳过模版库入库",
            "skipped": True,
        }
        return out
    path = str(file_path or "").strip()
    if not path or not os.path.isfile(path):
        out["template_ingest"] = {
            "success": False,
            "ingested": False,
            "message": "缺少可解析文件路径，无法入库模版库",
            "error_code": "missing_file",
        }
        return out
    try:
        ingest_payload, _code = ingest_office_path_to_template_library(
            path,
            template_name=template_name,
            template_scope=template_scope,
            source=source,
        )
    except RECOVERABLE_ERRORS as exc:
        logger.warning("ETL 后模版库入库异常: %s", exc)
        ingest_payload = {
            "success": False,
            "ingested": False,
            "message": f"模版库入库异常：{exc}",
        }
    out["template_ingest"] = ingest_payload
    return out


class OfficeTemplateIngestApplicationService:
    def ingest_bytes(self, **kwargs: Any) -> tuple[dict[str, Any], int]:
        return ingest_office_bytes_to_template_library(**kwargs)

    def ingest_path(self, file_path: str | Path, **kwargs: Any) -> tuple[dict[str, Any], int]:
        return ingest_office_path_to_template_library(file_path, **kwargs)


_svc: OfficeTemplateIngestApplicationService | None = None


def get_office_template_ingest_app_service() -> OfficeTemplateIngestApplicationService:
    global _svc
    if _svc is None:
        _svc = OfficeTemplateIngestApplicationService()
    return _svc
