# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.services.tools_workflow_registered")


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
            if not isinstance(preview_data, dict):
                preview_data = {}
            sheets = (
                preview_data.get("all_sheets")
                if isinstance(preview_data.get("all_sheets"), list)
                else []
            )
        sheet_index = params.get("sheet_index")
        sheet_name = str(params.get("sheet_name") or "").strip()
        if sheet_index is None:
            text_message = str(params.get("order_text") or runtime_context.get("message") or "")
            m = re.search("第\\s*(\\d+)\\s*(个)?\\s*(sheet|表)", text_message, flags=re.I)
            if m:
                try:
                    sheet_index = int(m.group(1))
                except _facade().RECOVERABLE_ERRORS:
                    sheet_index = None
        selected_sheet = None
        if isinstance(sheet_index, int) and sheet_index > 0:
            for s in sheets or []:
                if int(s.get("sheet_index") or 0) == sheet_index:
                    selected_sheet = s
                    break
        if selected_sheet is None and sheet_name:
            for s in sheets or []:
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
            "sample_rows": selected_sheet.get("sample_rows")
            if isinstance(selected_sheet.get("sample_rows"), list)
            else [],
            "grid_preview": selected_sheet.get("grid_preview")
            if isinstance(selected_sheet.get("grid_preview"), dict)
            else {},
            "grid_style_cache": selected_sheet.get("style_cache")
            if isinstance(selected_sheet.get("style_cache"), dict)
            else {},
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
        from app.infrastructure.templates.tenant_scope import templates_tenant_id_for_insert
        from app.infrastructure.tenant_scope import TenantScopeError

        try:
            tenant_id = templates_tenant_id_for_insert()
        except TenantScopeError:
            return {"success": False, "message": "缺少租户上下文，无法创建模板"}
        with get_db() as db:
            result = db.execute(
                text(
                    "\n                    INSERT INTO templates (\n                        template_key, template_name, template_type,\n                        original_file_path, analyzed_data, editable_config,\n                        zone_config, merged_cells_config, style_config,\n                        business_rules, is_active, tenant_id\n                    ) VALUES (\n                        :template_key, :template_name, :template_type,\n                        :original_file_path, :analyzed_data, :editable_config,\n                        :zone_config, :merged_cells_config, :style_config,\n                        :business_rules, :is_active, :tenant_id\n                    )\n                "
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
                    "tenant_id": tenant_id,
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
    return {"success": False, "message": f"未注册的 template_preview 动作: {action}"}


def _registered_router_print(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if action == "workflow_label_dispatch":
        from app.application.print_app_service import get_print_application_service

        model_number = str(params.get("model_number") or "").strip()
        if not model_number:
            return {"success": False, "message": "model_number 不能为空"}
        quantity = max(1, min(100, int(params.get("quantity") or 1)))
        product_name = model_number
        specification: str | None = None
        unit = "个"
        try:
            from app.application import get_product_app_service

            products_result = get_product_app_service().search_products(
                keyword=model_number, filters={"per_page": 1}
            )
            products = (
                products_result.get("data") or []
                if isinstance(products_result, dict)
                else products_result
            )
            if isinstance(products, list) and products:
                product = products[0]
                if isinstance(product, dict):
                    product_name = str(
                        product.get("name") or product.get("product_name") or model_number
                    )
                    specification = (
                        str(product.get("specification") or product.get("spec") or "") or None
                    )
                    unit = str(product.get("unit") or "个")
        except _facade().RECOVERABLE_ERRORS as lookup_err:
            _facade().logger.warning("print.workflow_label_dispatch: 产品查找失败: %s", lookup_err)
        return dict(
            get_print_application_service().print_single_label(
                product_name=product_name,
                model_number=model_number or None,
                specification=specification,
                unit=unit,
                quantity=quantity,
            )
            or {}
        )
    if str(runtime_context.get("service_source") or "") == "fastapi_print_route":
        from app.fastapi_routes import print_routes

        svc = print_routes._svc()
    else:
        from app.services import get_printer_service

        svc = get_printer_service()
    if action == "view":
        return {"success": True, "redirect": "/console?view=print"}
    if action in ("list", "query"):
        return _facade().cast("dict[Any, Any]", svc.get_printers())
    if action == "print_label":
        return _facade().cast(
            "dict[Any, Any]",
            svc.print_label(
                str(params.get("file_path") or "").strip(),
                params.get("printer_name"),
                int(params.get("copies") or 1),
            ),
        )
    if action == "print_document":
        return _facade().cast(
            "dict[Any, Any]",
            svc.print_document(
                str(params.get("file_path") or "").strip(),
                params.get("printer_name"),
                bool(params.get("use_automation", False)),
            ),
        )
    if action == "test":
        return _facade().cast(
            "dict[Any, Any]", svc.test_printer(str(params.get("printer_name") or "").strip())
        )
    if action == "save_printer_selection":
        document_printer = params.get("document_printer")
        label_printer = params.get("label_printer")
        printers_result = dict(svc.get_printers() or {})
        printers = printers_result.get("printers", [])
        if not isinstance(printers, list):
            printers = []
        available_names = {
            (printer.get("name") or "").strip() for printer in printers if isinstance(printer, dict)
        }

        def is_valid(name: _facade().Any) -> bool:
            if name is None:
                return True
            value = str(name).strip()
            return value == "" or value in available_names

        if not is_valid(document_printer):
            return {"success": False, "message": "发货单打印机不在当前可用打印机列表中"}
        if not is_valid(label_printer):
            return {"success": False, "message": "标签打印机不在当前可用打印机列表中"}
        result = dict(
            svc.save_printer_selection(
                document_printer=str(document_printer).strip()
                if document_printer is not None
                else None,
                label_printer=str(label_printer).strip() if label_printer is not None else None,
            )
            or {}
        )
        result.update(dict(svc.classify_printers(printers) or {}))
        return result
    return {"success": False, "message": f"未注册的 print 动作: {action}"}


def _registered_router_printer_list(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    from app.services import get_system_service

    svc = get_system_service()
    if action == "view":
        return {"success": True, "redirect": "/console?view=printer-list"}
    if action in ("list", "query"):
        return svc.get_printer_config()
    if action == "set_default":
        return svc.set_default_printer(str(params.get("printer_name") or "").strip())
    return {"success": False, "message": f"未注册的 printer_list 动作: {action}"}


def _registered_router_settings(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    from app.services import get_system_service

    svc = get_system_service()
    if action == "view":
        return {"success": True, "redirect": "/console?view=settings"}
    if action in ("query", "get_system_info"):
        return {"success": True, "data": svc.get_system_info()}
    if action == "get_startup_config":
        return {"success": True, "data": svc.get_startup_config()}
    if action == "enable_startup":
        return svc.enable_startup()
    if action == "disable_startup":
        return svc.disable_startup()
    return {"success": False, "message": f"未注册的 settings 动作: {action}"}
