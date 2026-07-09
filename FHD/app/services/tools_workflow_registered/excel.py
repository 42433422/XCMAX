"""Excel and template workflow routers."""

from __future__ import annotations

import logging

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

def _registered_router_excel_analyzer(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if action != "analyze":
        return {"success": False, "message": f"未知 excel_analyzer action: {action}"}
    file_path = str(params.get("file_path") or "").strip()
    if not file_path:
        return {"success": False, "message": "excel_analyzer.analyze 缺少 file_path 参数"}
    try:
        from app.infrastructure.skills.excel_analyzer.excel_template_analyzer import (
            get_excel_analyzer_skill,
        )
    except ImportError:
        return {"success": False, "message": "Excel Analyzer Skill 未正确安装"}

    result = get_excel_analyzer_skill().execute(
        file_path=file_path,
        sheet_name=params.get("sheet_name"),
        output_json=params.get("output_json"),
    )
    if isinstance(result, dict):
        result.setdefault("file_path", file_path)
    return result if isinstance(result, dict) else {"success": False, "message": "技能返回值无效"}


def _registered_router_excel_toolkit(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    normalized = str(action or "view").strip().lower() or "view"
    if normalized not in {"view", "merged", "styles", "structure"}:
        return {"success": False, "message": f"未知 excel_toolkit action: {action}"}
    file_path = str(params.get("file_path") or "").strip()
    if not file_path:
        return {"success": False, "message": f"excel_toolkit.{normalized} 缺少 file_path 参数"}
    try:
        from app.infrastructure.skills.excel_toolkit.excel_toolkit import get_excel_toolkit_skill
    except ImportError:
        return {"success": False, "message": "Excel Toolkit Skill 未正确安装"}

    kwargs = {}
    if params.get("max_rows") is not None:
        kwargs["max_rows"] = params.get("max_rows")
    result = get_excel_toolkit_skill().execute(
        file_path=file_path,
        action=normalized,
        sheet_name=params.get("sheet_name"),
        **kwargs,
    )
    if isinstance(result, dict):
        result.setdefault("file_path", file_path)
    return result if isinstance(result, dict) else {"success": False, "message": "技能返回值无效"}


def _registered_router_label_template_generator(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if action != "execute":
        return {"success": False, "message": f"未知 label_template_generator action: {action}"}
    image_path = str(params.get("image_path") or "").strip()
    if not image_path:
        return {
            "success": False,
            "message": "label_template_generator.execute 缺少 image_path 参数",
        }
    try:
        from app.infrastructure.skills.label_template_generator import (
            get_label_template_generator_skill,
        )
    except ImportError:
        return {"success": False, "message": "Label Template Generator Skill 未正确安装"}

    result = get_label_template_generator_skill().execute(
        image_path=image_path,
        class_name=params.get("class_name") or "LabelTemplateGenerator",
        output_file=params.get("output_file"),
        enable_ocr=bool(params.get("enable_ocr", True)),
        verbose=bool(params.get("verbose", False)),
    )
    if isinstance(result, dict):
        result.setdefault("image_path", image_path)
    return result if isinstance(result, dict) else {"success": False, "message": "技能返回值无效"}


def _registered_router_document_template(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    payload = dict(params or {})
    if action == "create":
        from app.fastapi_routes.document_templates_compat import run_archive_template_create

        data, status_code = run_archive_template_create(payload)
    elif action == "update":
        from app.fastapi_routes.document_templates_compat import run_archive_template_update

        data, status_code = run_archive_template_update(payload)
    elif action == "delete":
        from app.fastapi_routes.document_templates_compat import run_archive_template_delete

        data, status_code = run_archive_template_delete(
            payload,
            base_dir=str(runtime_context.get("template_base_dir") or "") or None,
        )
    else:
        return {"success": False, "message": f"未知 document_template action: {action}"}
    result = dict(data or {})
    result["http_status_code"] = int(status_code or (200 if result.get("success") else 400))
    return result


def _registered_router_template_preview(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if action == "view":
        return {"success": True, "redirect": "/console?view=template-preview"}
    from app.application import get_template_app_service

    svc = get_template_app_service()
    if action in ("list", "query"):
        result = svc.get_templates()
        if isinstance(result, dict):
            return result
        return {"success": True, "data": result}
    if action == "create":
        import json
        import re
        import uuid
        from datetime import datetime

        from sqlalchemy import text

        from app.db.session import get_db
        from app.services.document_templates_service import (
            _ensure_template_tables_ready,
            _infer_business_scope,
            _validate_required_terms,
        )

        excel_analysis = params.get("excel_analysis")
        if not isinstance(excel_analysis, dict):
            excel_analysis = runtime_context.get("excel_analysis")
        if not isinstance(excel_analysis, dict):
            fallback_ctx = runtime_context.get("last_excel_analysis_context")
            if isinstance(fallback_ctx, dict):
                excel_analysis = (
                    fallback_ctx.get("result")
                    if isinstance(fallback_ctx.get("result"), dict)
                    else fallback_ctx
                )
        excel_analysis = excel_analysis if isinstance(excel_analysis, dict) else {}

        sheets = excel_analysis.get("sheets")
        if not isinstance(sheets, list):
            preview_data = (
                excel_analysis.get("preview_data")
                if isinstance(excel_analysis.get("preview_data"), dict)
                else {}
            )
            sheets = (
                preview_data.get("all_sheets")
                if isinstance(preview_data.get("all_sheets"), list)
                else []
            )

        sheet_index = params.get("sheet_index")
        sheet_name = str(params.get("sheet_name") or "").strip()
        if sheet_index is None:
            text_message = str(params.get("order_text") or runtime_context.get("message") or "")
            m = re.search(r"第\s*(\d+)\s*(个)?\s*(sheet|表)", text_message, flags=re.I)
            if m:
                try:
                    sheet_index = int(m.group(1))
                except RECOVERABLE_ERRORS:
                    sheet_index = None

        selected_sheet = None
        if isinstance(sheet_index, int) and sheet_index > 0:
            for s in sheets:
                if int(s.get("sheet_index") or 0) == sheet_index:
                    selected_sheet = s
                    break
        if selected_sheet is None and sheet_name:
            for s in sheets:
                if str(s.get("sheet_name") or "").strip() == sheet_name:
                    selected_sheet = s
                    break
        if selected_sheet is None and sheets:
            selected_sheet = sheets[0]

        if not selected_sheet:
            return {"success": False, "message": "未找到可用的 sheet 分析结果，请先执行分析Excel。"}

        picked_sheet_name = str(selected_sheet.get("sheet_name") or "").strip() or "Sheet1"
        template_name = str(params.get("name") or params.get("template_name") or "").strip()
        if not template_name:
            template_name = f"{picked_sheet_name}-模板"

        fields = (
            selected_sheet.get("fields") if isinstance(selected_sheet.get("fields"), list) else []
        )
        preview_data = {
            "sheet_name": picked_sheet_name,
            "selected_sheet_name": picked_sheet_name,
            "sample_rows": (
                selected_sheet.get("sample_rows")
                if isinstance(selected_sheet.get("sample_rows"), list)
                else []
            ),
            "grid_preview": (
                selected_sheet.get("grid_preview")
                if isinstance(selected_sheet.get("grid_preview"), dict)
                else {}
            ),
            "grid_style_cache": (
                selected_sheet.get("style_cache")
                if isinstance(selected_sheet.get("style_cache"), dict)
                else {}
            ),
        }
        template_type = str(params.get("template_type") or "Excel").strip()
        business_scope = str(
            params.get("business_scope") or _infer_business_scope(template_type) or ""
        ).strip()
        source = str(params.get("source") or "ai-natural-language").strip() or "ai-natural-language"
        file_path = (
            str(params.get("file_path") or excel_analysis.get("file_path") or "").strip() or None
        )

        if business_scope:
            valid, missing_terms = _validate_required_terms({}, fields, business_scope)
            if not valid:
                return {
                    "success": False,
                    "message": "必填字段未匹配，不能保存模板",
                    "business_scope": business_scope,
                    "missing_terms": missing_terms,
                }

        analyzed_data = {
            "category": "excel",
            "source": source,
            "business_scope": business_scope,
            "fields": fields,
            "preview_data": preview_data,
        }
        editable_config = fields
        business_rules = {
            "business_scope": business_scope,
            "source": source,
            "selected_sheet_name": picked_sheet_name,
        }

        _ensure_template_tables_ready()
        template_key = (
            f"TPL_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8].upper()}"
        )
        with get_db() as db:
            result = db.execute(
                text(
                    """
                    INSERT INTO templates (
                        template_key, template_name, template_type,
                        original_file_path, analyzed_data, editable_config,
                        zone_config, merged_cells_config, style_config,
                        business_rules, is_active
                    ) VALUES (
                        :template_key, :template_name, :template_type,
                        :original_file_path, :analyzed_data, :editable_config,
                        :zone_config, :merged_cells_config, :style_config,
                        :business_rules, :is_active
                    )
                """
                ),
                {
                    "template_key": template_key,
                    "template_name": template_name,
                    "template_type": template_type,
                    "original_file_path": file_path,
                    "analyzed_data": json.dumps(analyzed_data, ensure_ascii=False),
                    "editable_config": json.dumps(editable_config, ensure_ascii=False),
                    "zone_config": json.dumps({}, ensure_ascii=False),
                    "merged_cells_config": json.dumps({}, ensure_ascii=False),
                    "style_config": json.dumps({}, ensure_ascii=False),
                    "business_rules": json.dumps(business_rules, ensure_ascii=False),
                    "is_active": 1,
                },
            )
            template_id = result.lastrowid
            db.commit()

        return {
            "success": True,
            "message": "已按指定 sheet 加入模板库",
            "template": {
                "id": f"db:{template_id}",
                "db_id": template_id,
                "name": template_name,
                "template_type": template_type,
                "business_scope": business_scope,
                "source": source,
                "fields": fields,
                "preview_data": preview_data,
            },
        }


