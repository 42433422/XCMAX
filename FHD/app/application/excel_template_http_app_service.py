"""Excel 模板 HTTP 应用服务（自 fastapi_routes/excel_templates 下沉）。"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Body, File, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text

from app.application import excel_template_decompose as _decompose
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import get_app_data_dir

logger = logging.getLogger(__name__)

_TEMPLATE_SERVICE_UNAVAILABLE = "模板服务暂时不可用，请稍后重试"

_REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = str(_REPO_ROOT / "templates")
TEMP_EXCEL_DIR = os.path.join(get_app_data_dir(), "temp_excel")
os.makedirs(TEMP_EXCEL_DIR, exist_ok=True)


def get_base_dir() -> str:
    return str(_REPO_ROOT)


def _map_template_category(template_type: str) -> str:
    t = (template_type or "").strip().lower()
    if any(k in t for k in ["标签", "label", "print", "打印"]):
        return "label_print"
    return "excel"


def _normalize_template_dto(template: dict) -> dict:
    tpl = dict(template or {})
    template_type = tpl.get("template_type", "")
    category = tpl.get("category") or _map_template_category(str(template_type))
    file_path = tpl.get("file_path") or tpl.get("path")
    lower_fp = str(file_path or "").lower()
    if lower_fp.endswith((".docx", ".doc")):
        category = "word"
    normalized = {
        **tpl,
        "category": category,
        "file_path": file_path,
        "is_active": bool(tpl.get("is_active", True)),
        "preview_capable": bool(file_path and tpl.get("exists", False)),
    }
    return normalized


def _resolve_template_path(filename: str) -> str | None:
    base_dir = get_base_dir()
    path = os.path.join(base_dir, filename)
    if os.path.exists(path):
        return path
    alt_path = os.path.join(TEMPLATE_DIR, filename)
    if os.path.exists(alt_path):
        return alt_path
    return path if os.path.exists(path) else None


def _get_template_list():
    from app.application import get_template_app_service

    return get_template_app_service().get_templates().get("templates", [])


_decompose_from_grid = _decompose.decompose_from_grid
_decompose_template_openpyxl = _decompose.decompose_template_openpyxl
_decompose_template_xls_pandas = _decompose.decompose_template_xls_pandas
_is_unreadable_workbook_error = _decompose.is_unreadable_workbook_error
_json_safe_cell_value = _decompose.json_safe_cell_value
_pick_sheet_name = _decompose.pick_sheet_name


def _decompose_template(file_path, sheet_name=None, sample_rows=5) -> tuple[dict, int]:
    try:
        if not os.path.exists(file_path):
            return {"success": False, "message": "模板文件不存在"}, 404

        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".xls":
            return _decompose_template_xls_pandas(file_path, sheet_name, sample_rows)

        try:
            return _decompose_template_openpyxl(file_path, sheet_name, sample_rows)
        except RECOVERABLE_ERRORS as error:
            if _is_unreadable_workbook_error(str(error)):
                return {
                    "success": False,
                    "message": "模板文件损坏或格式异常，无法读取。请重新导出或另存为 .xlsx 后重试。",
                    "error_code": "UNREADABLE_WORKBOOK",
                }, 200
            raise
    except RECOVERABLE_ERRORS as error:
        logger.exception("分解 Excel 模板失败")
        if _is_unreadable_workbook_error(str(error)):
            return {
                "success": False,
                "message": "模板文件损坏或格式异常，无法读取。请重新导出或另存为 .xlsx 后重试。",
                "error_code": "UNREADABLE_WORKBOOK",
            }, 200
        return {"success": False, "message": _TEMPLATE_SERVICE_UNAVAILABLE}, 500


def list_templates_get():
    """与归档中后注册的 list_templates 一致（规范化 DTO）。"""
    try:
        templates = [_normalize_template_dto(t) for t in _get_template_list()]
        return JSONResponse({"success": True, "templates": templates}, status_code=200)
    except RECOVERABLE_ERRORS:
        logger.exception("获取模板列表失败")
        return JSONResponse(
            {"success": False, "message": _TEMPLATE_SERVICE_UNAVAILABLE}, status_code=500
        )


def get_templates_list():
    try:
        templates = _get_template_list()
        return JSONResponse({"success": True, "templates": templates})
    except RECOVERABLE_ERRORS:
        logger.exception("获取模板列表失败")
        return JSONResponse(
            {"success": False, "message": _TEMPLATE_SERVICE_UNAVAILABLE}, status_code=500
        )


def list_templates_by_type(
    type: str = Query(default="发货单"),
    active_only: str = Query(default="true"),
):
    try:
        from app.application import get_template_app_service

        active = active_only.lower() == "true"
        svc = get_template_app_service()
        templates = [_normalize_template_dto(t) for t in svc.list_by_type(type, active_only=active)]
        return JSONResponse(
            {"success": True, "templates": templates, "count": len(templates)}, status_code=200
        )
    except RECOVERABLE_ERRORS:
        logger.exception("按类型获取模板列表失败")
        return JSONResponse(
            {"success": False, "message": _TEMPLATE_SERVICE_UNAVAILABLE}, status_code=500
        )


def get_default_template(type: str = Query(default="发货单")):
    try:
        from app.application import get_template_app_service

        svc = get_template_app_service()
        tpl = svc.get_default_for_type(type)
        if not tpl:
            return JSONResponse({"success": False, "message": "暂无可用模板"}, status_code=404)
        return JSONResponse(
            {"success": True, "template": _normalize_template_dto(tpl)}, status_code=200
        )
    except RECOVERABLE_ERRORS:
        logger.exception("获取默认模板失败")
        return JSONResponse(
            {"success": False, "message": _TEMPLATE_SERVICE_UNAVAILABLE}, status_code=500
        )


def get_template_file(template_id: str):
    try:
        templates = _get_template_list()
        template = next((t for t in templates if t["id"] == template_id), None)
        if not template:
            return JSONResponse({"success": False, "message": "模板不存在"}, status_code=404)
        if not template.get("exists") or not template.get("path"):
            return JSONResponse({"success": False, "message": "模板文件不存在"}, status_code=404)
        return FileResponse(
            template["path"],
            filename=template["filename"],
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except RECOVERABLE_ERRORS:
        logger.exception("获取模板文件失败")
        return JSONResponse(
            {"success": False, "message": _TEMPLATE_SERVICE_UNAVAILABLE}, status_code=500
        )


def save_template(data: dict[str, Any] = Body(default_factory=dict)):
    try:
        from app.application import get_template_app_service

        source_name = data.get("source_name", "尹玉华132.xlsx")
        target_name = data.get("target_name", "发货单模板.xlsx")
        overwrite = bool(data.get("overwrite", False))
        result = get_template_app_service().save_template_file(source_name, target_name, overwrite)
        status = 200 if result.get("success") else 404
        return JSONResponse(result, status_code=status)
    except RECOVERABLE_ERRORS:
        logger.exception("保存模板失败")
        return JSONResponse(
            {"success": False, "message": _TEMPLATE_SERVICE_UNAVAILABLE}, status_code=500
        )


def decompose_template(data: dict[str, Any] = Body(default_factory=dict)):
    try:
        filename = data.get("filename")
        file_path = data.get("file_path")
        sheet_name = data.get("sheet_name")
        sample_rows = data.get("sample_rows", 5)
        if file_path:
            target_path = file_path
        elif filename:
            target_path = _resolve_template_path(filename)
        else:
            return JSONResponse(
                {"success": False, "message": "请提供 filename 或 file_path"}, status_code=400
            )
        if not target_path or not os.path.exists(target_path):
            return JSONResponse({"success": False, "message": "模板文件不存在"}, status_code=404)
        result, status = _decompose_template(target_path, sheet_name, sample_rows)
        return JSONResponse(result, status_code=status)
    except RECOVERABLE_ERRORS:
        logger.exception("分解模板失败")
        return JSONResponse(
            {"success": False, "message": _TEMPLATE_SERVICE_UNAVAILABLE}, status_code=500
        )


async def upload_excel(excel_file: UploadFile | None = File(default=None)):
    try:
        if excel_file is None or not excel_file.filename:
            return JSONResponse({"success": False, "message": "请上传 Excel 文件"}, status_code=400)
        if not excel_file.filename.lower().endswith((".xlsx", ".xls")):
            return JSONResponse(
                {"success": False, "message": "只支持 .xlsx 和 .xls 格式"}, status_code=400
            )
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"excel_{timestamp}_{excel_file.filename}"
        file_path = os.path.join(TEMP_EXCEL_DIR, filename)
        body = await excel_file.read()
        with open(file_path, "wb") as f:
            f.write(body)
        logger.info("Excel 文件已上传: %s", file_path)
        return JSONResponse(
            {
                "success": True,
                "file_path": file_path,
                "filename": excel_file.filename,
                "message": "文件上传成功",
            }
        )
    except RECOVERABLE_ERRORS:
        logger.exception("上传 Excel 文件失败")
        return JSONResponse(
            {"success": False, "message": _TEMPLATE_SERVICE_UNAVAILABLE}, status_code=500
        )


def excel_templates_test():
    return JSONResponse(
        {
            "success": True,
            "message": "Excel 模板服务运行正常",
            "timestamp": datetime.now().isoformat(),
        }
    )


def get_template(template_id: int):
    try:
        from app.db.session import get_db
        from app.infrastructure.templates.tenant_scope import templates_tenant_where_sql

        tenant_sql, tenant_bind = templates_tenant_where_sql()
        with get_db() as db:
            result = db.execute(
                text(
                    f"SELECT * FROM templates WHERE id = :id AND is_active = 1 AND ({tenant_sql})"
                ),
                {"id": template_id, **tenant_bind},
            )
            row = result.fetchone()
            if not row:
                return JSONResponse({"success": False, "message": "模板不存在"}, status_code=404)
            template = {
                "id": row.id,
                "template_key": row.template_key,
                "template_name": row.template_name,
                "template_type": row.template_type,
                "original_file_path": row.original_file_path,
                "analyzed_data": json.loads(row.analyzed_data) if row.analyzed_data else None,
                "editable_config": json.loads(row.editable_config) if row.editable_config else None,
                "zone_config": json.loads(row.zone_config) if row.zone_config else None,
                "merged_cells_config": (
                    json.loads(row.merged_cells_config) if row.merged_cells_config else None
                ),
                "style_config": json.loads(row.style_config) if row.style_config else None,
                "business_rules": json.loads(row.business_rules) if row.business_rules else None,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
            return JSONResponse({"success": True, "template": template})
    except RECOVERABLE_ERRORS:
        logger.exception("获取模板详情失败")
        return JSONResponse(
            {"success": False, "message": _TEMPLATE_SERVICE_UNAVAILABLE}, status_code=500
        )


def update_template(template_id: int, data: dict[str, Any] = Body(default_factory=dict)):
    try:
        from app.db.session import get_db
        from app.infrastructure.templates.tenant_scope import templates_tenant_where_sql

        tenant_sql, tenant_bind = templates_tenant_where_sql()
        with get_db() as db:
            result = db.execute(
                text(f"SELECT id FROM templates WHERE id = :id AND ({tenant_sql})"),
                {"id": template_id, **tenant_bind},
            )
            if not result.fetchone():
                return JSONResponse({"success": False, "message": "模板不存在"}, status_code=404)
            updates = []
            params: dict[str, Any] = {"id": template_id, **tenant_bind}
            if "template_name" in data:
                updates.append("template_name = :template_name")
                params["template_name"] = data["template_name"]
            if "template_type" in data:
                updates.append("template_type = :template_type")
                params["template_type"] = data["template_type"]
            if "editable_config" in data:
                updates.append("editable_config = :editable_config")
                params["editable_config"] = json.dumps(data["editable_config"], ensure_ascii=False)
            if "zone_config" in data:
                updates.append("zone_config = :zone_config")
                params["zone_config"] = json.dumps(data["zone_config"], ensure_ascii=False)
            if "business_rules" in data:
                updates.append("business_rules = :business_rules")
                params["business_rules"] = json.dumps(data["business_rules"], ensure_ascii=False)
            updates.append("updated_at = :updated_at")
            params["updated_at"] = datetime.now()
            sql = (
                "UPDATE templates SET " + ", ".join(updates) + f" WHERE id = :id AND ({tenant_sql})"
            )
            db.execute(text(sql), params)
            db.commit()
            db.execute(
                text(
                    """
                    INSERT INTO template_usage_log (template_id, action, result)
                    VALUES (:template_id, 'update', :result)
                """
                ),
                {"template_id": template_id, "result": "更新模板配置"},
            )
            db.commit()
        return JSONResponse({"success": True, "message": "模板更新成功"})
    except RECOVERABLE_ERRORS:
        logger.exception("更新模板失败")
        return JSONResponse(
            {"success": False, "message": _TEMPLATE_SERVICE_UNAVAILABLE}, status_code=500
        )


def delete_template(template_id: int):
    try:
        from app.db.session import get_db
        from app.infrastructure.templates.tenant_scope import templates_tenant_where_sql

        tenant_sql, tenant_bind = templates_tenant_where_sql()
        with get_db() as db:
            result = db.execute(
                text(f"SELECT id FROM templates WHERE id = :id AND ({tenant_sql})"),
                {"id": template_id, **tenant_bind},
            )
            if not result.fetchone():
                return JSONResponse({"success": False, "message": "模板不存在"}, status_code=404)
            db.execute(
                text(
                    f"UPDATE templates SET is_active = 0, updated_at = :updated_at "
                    f"WHERE id = :id AND ({tenant_sql})"
                ),
                {"id": template_id, "updated_at": datetime.now(), **tenant_bind},
            )
            db.execute(
                text(
                    """
                    INSERT INTO template_usage_log (template_id, action, result)
                    VALUES (:template_id, 'delete', :result)
                """
                ),
                {"template_id": template_id, "result": "删除模板"},
            )
            db.commit()
        return JSONResponse({"success": True, "message": "模板删除成功"})
    except RECOVERABLE_ERRORS:
        logger.exception("删除模板失败")
        return JSONResponse(
            {"success": False, "message": _TEMPLATE_SERVICE_UNAVAILABLE}, status_code=500
        )
