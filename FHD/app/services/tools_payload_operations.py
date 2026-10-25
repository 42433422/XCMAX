"""Operational, document, print, and system legacy tool handlers."""

from __future__ import annotations

import logging
import os

from app.services.tools_payload_dispatch_common import NOT_HANDLED
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def dispatch_operational_tool_payload(
    tool_id,
    action: str,
    params: dict,
    *,
    json_response_fn,
    hdr_getter,
    parse_order_text_fn,
):
    _j = json_response_fn
    _parse_order_text = parse_order_text_fn
    _ = hdr_getter
    if tool_id == "orders":
        if action == "view":
            return _j({"success": True, "redirect": "/console?view=shipment-orders"})
        return _j({"success": True, "message": "出货单"})

    elif tool_id == "shipment_generate":
        if action == "view":
            return _j({"success": True, "redirect": "/console?view=shipment"})

        # 真正调用发货单生成 API
        try:
            order_text = params.get("order_text", "")
            direct_products = params.get("products") or []
            direct_unit_name = (params.get("unit_name") or "").strip()
            custom_order_number = (params.get("order_number") or "").strip()

            logger.info("收到发货单生成请求：order_text=%s", order_text)

            from app.services.shipment_number_mode_service import ShipmentNumberModeService

            number_mode_service = ShipmentNumberModeService()
            payload, status_code = number_mode_service.execute(
                order_text=order_text,
                custom_order_number=custom_order_number,
                direct_unit_name=direct_unit_name,
                direct_products=direct_products if isinstance(direct_products, list) else [],
                parse_order_text=_parse_order_text,
                template_name=params.get("template_name") or params.get("template"),
                template_id=params.get("template_id"),
                preferred_template=params.get("preferred_template") or params.get("template"),
            )
            return _j(payload, status_code)

        except RECOVERABLE_ERRORS as e:
            logger.error("生成发货单失败：%s", e, exc_info=True)
            return _j({"success": False, "message": f"生成失败：{str(e)}"}, 500)
    elif tool_id == "print":
        from app.services import get_printer_service

        printer_service = get_printer_service()
        if action == "view":
            return _j({"success": True, "redirect": "/console?view=print"})
        if action in ("list", "query"):
            return _j(printer_service.get_printers(), 200)
        if action == "print_label":
            result = printer_service.print_label(
                str(params.get("file_path") or "").strip(),
                params.get("printer_name"),
                int(params.get("copies") or 1),
            )
            return _j(result, 200)
        if action == "print_document":
            result = printer_service.print_document(
                str(params.get("file_path") or "").strip(),
                params.get("printer_name"),
                bool(params.get("use_automation", False)),
            )
            return _j(result, 200)
        if action == "test":
            result = printer_service.test_printer(str(params.get("printer_name") or "").strip())
            return _j(result, 200)
        return _j({"success": True, "message": "标签打印"})

    elif tool_id == "printer_list":
        if action in ("list", "query"):
            from app.services import get_system_service

            return _j(get_system_service().get_printer_config(), 200)
        if action == "set_default":
            from app.services import get_system_service

            return _j(
                get_system_service().set_default_printer(
                    str(params.get("printer_name") or "").strip()
                ),
                200,
            )
        return _j(
            {
                "success": True,
                "redirect": "/console?view=printer-list",
                "message": "已打开打印机列表",
            }
        )

    elif tool_id == "materials":
        from app.application import get_material_application_service

        svc = get_material_application_service()
        if action == "view":
            return _j({"success": True, "redirect": "/console?view=materials"})
        if action in ("list", "query"):
            return (
                _j(
                    svc.get_all_materials(
                        search=str(params.get("search") or params.get("keyword") or "").strip(),
                        category=str(params.get("category") or "").strip() or None,
                        page=int(params.get("page") or 1),
                        per_page=int(params.get("per_page") or 20),
                    )
                ),
                200,
            )
        if action == "create":
            return _j(svc.create_material(dict(params or {})), 200)
        if action == "update":
            material_id = int(params.get("id") or 0)
            payload = {k: v for k, v in params.items() if k != "id"}
            return _j(svc.update_material(material_id, **payload), 200)
        if action == "delete":
            return _j(svc.delete_material(int(params.get("id") or 0)), 200)
        if action == "batch_delete":
            ids = [
                int(x)
                for x in (params.get("ids") or params.get("material_ids") or [])
                if str(x).strip()
            ]
            return _j(svc.batch_delete_materials(ids), 200)
        if action == "export":
            return (
                _j(
                    svc.export_to_excel(
                        search=str(params.get("search") or params.get("keyword") or "").strip()
                        or None,
                        category=str(params.get("category") or "").strip() or None,
                        template_id=params.get("template_id"),
                    )
                ),
                200,
            )
        return _j({"success": True, "message": "原材料仓库"})

    elif tool_id == "ocr":
        if action == "view":
            return _j({"success": True, "redirect": "/console?view=ocr"})
        return _j({"success": True, "message": "图片 OCR"})

    elif tool_id == "excel_decompose":
        if action == "view":
            return _j({"success": True, "redirect": "/console?view=excel"})
        return _j({"success": True, "message": "Excel 模板分解"})

    elif tool_id == "excel_analyzer":
        file_path = str(params.get("file_path") or "")
        sheet_name = params.get("sheet_name")
        output_json = params.get("output_json")

        if not file_path:
            return _j({"success": False, "message": "缺少参数：file_path（Excel文件路径）"}, 400)
        try:
            from app.infrastructure.skills.excel_analyzer.excel_template_analyzer import (  # noqa: F401
                ExcelAnalyzerSkill,
                get_excel_analyzer_skill,
            )

            analyzer_skill = get_excel_analyzer_skill()
            result = analyzer_skill.execute(
                file_path=file_path, sheet_name=sheet_name, output_json=output_json
            )
            return _j(result)
        except ImportError:
            return _j(
                {"success": False, "message": "Excel分析技能未正确安装，请检查openpyxl库"}, 500
            )
        except RECOVERABLE_ERRORS as e:
            logger.error("Excel Analyzer执行失败: %s", e)
            return _j({"success": False, "message": f"分析失败: {str(e)}"}, 500)
    elif tool_id == "template_extract":
        if action in (None, "", "view"):
            return _j(
                {
                    "success": True,
                    "redirect": "/console?view=business-docking",
                    "message": "请先上传 Excel 并提取模板",
                },
                200,
            )
        file_path = str(params.get("file_path") or "").strip()
        sheet_name = str(params.get("sheet_name") or "").strip() or None

        if not file_path:
            return _j({"success": False, "message": "缺少参数：file_path（Excel文件路径）"}, 400)
        try:
            from app.services.document_templates_service import (
                _extract_excel_grid_preview,
                _extract_structured_excel_preview,
                _list_excel_sheet_names,
            )

            if not os.path.exists(file_path):  # noqa: F823
                return _j({"success": False, "message": f"文件不存在：{file_path}"}, 404)
            sheet_names = _list_excel_sheet_names(file_path)
            structured = _extract_structured_excel_preview(
                file_path, sheet_name=sheet_name, sample_limit=8
            )
            grid_preview = _extract_excel_grid_preview(
                file_path, sheet_name=sheet_name, max_rows=24, max_cols=14
            )
            selected_sheet_name = (
                structured.get("sheet_name")
                or grid_preview.get("sheet_name")
                or sheet_name
                or (sheet_names[0] if sheet_names else "")
            )
            template_name = os.path.splitext(os.path.basename(file_path))[0]

            return _j(
                {
                    "success": True,
                    "template_name": template_name,
                    "template_type": "excel",
                    "file_path": file_path,
                    "fields": structured.get("fields") or [],
                    "preview_data": {
                        "sample_rows": structured.get("sample_rows") or [],
                        "sheet_name": structured.get("sheet_name") or sheet_name or "",
                        "selected_sheet_name": selected_sheet_name,
                        "sheet_names": sheet_names,
                        "grid_preview": grid_preview,
                        "file_path": file_path,
                    },
                },
                200,
            )
        except RECOVERABLE_ERRORS as e:
            logger.error("template_extract 执行失败: %s", e, exc_info=True)
            return _j({"success": False, "message": f"提取失败: {str(e)}"}, 500)
    elif tool_id == "excel_toolkit":
        file_path = str(params.get("file_path") or "")
        sheet_name = params.get("sheet_name")
        toolkit_action = str(params.get("action") or "view")

        if not file_path:
            return _j({"success": False, "message": "缺少参数：file_path（Excel文件路径）"}, 400)
        try:
            from app.infrastructure.skills.excel_toolkit.excel_toolkit import (  # noqa: F401
                ExcelToolkitSkill,
                get_excel_toolkit_skill,
            )

            toolkit_skill = get_excel_toolkit_skill()
            result = toolkit_skill.execute(
                file_path=file_path, action=toolkit_action, sheet_name=sheet_name
            )
            return _j(result)
        except ImportError:
            return _j(
                {"success": False, "message": "Excel工具技能未正确安装，请检查openpyxl库"}, 500
            )
        except RECOVERABLE_ERRORS as e:
            logger.error("Excel Toolkit执行失败: %s", e)
            return _j({"success": False, "message": f"执行失败: {str(e)}"}, 500)
    elif tool_id == "shipment_template":
        if action == "view":
            return _j({"success": True, "redirect": "/console?view=template-preview"})
        return _j({"success": True, "message": "发货单模板"})

    elif tool_id == "template_preview":
        if action in ("list", "query"):
            from app.application import get_template_app_service

            result = get_template_app_service().get_templates()
            if isinstance(result, dict):
                return _j(result, 200)
            return _j({"success": True, "data": result}, 200)
        return _j(
            {
                "success": True,
                "redirect": "/console?view=template-preview",
                "message": "已打开模板预览",
            }
        )

    elif tool_id == "settings":
        from app.services import get_system_service

        settings_svc = get_system_service()
        if action in ("query", "get_system_info"):
            return _j({"success": True, "data": settings_svc.get_system_info()}, 200)
        if action == "get_startup_config":
            return _j({"success": True, "data": settings_svc.get_startup_config()}, 200)
        if action == "enable_startup":
            return _j(settings_svc.enable_startup(), 200)
        if action == "disable_startup":
            return _j(settings_svc.disable_startup(), 200)
        return _j(
            {"success": True, "redirect": "/console?view=settings", "message": "已打开系统设置"}
        )

    elif tool_id == "tools_table":
        if action in ("list", "query"):
            from app.services.tools_execution_service import get_workflow_tool_registry

            return _j(
                {"success": True, "tool_ids": list(get_workflow_tool_registry().keys())},
                200,
            )
        return _j({"success": True, "redirect": "/console?view=tools", "message": "已打开工具表"})

    elif tool_id == "other_tools":
        if action in ("list", "query"):
            return _j(
                {
                    "success": True,
                    "tools": [
                        "database",
                        "ocr",
                        "excel_toolkit",
                        "excel_analyzer",
                        "template_extract",
                    ],
                },
                200,
            )
        return _j(
            {"success": True, "redirect": "/console?view=other-tools", "message": "已打开其他工具"}
        )

    elif tool_id == "database":
        from app.services import get_database_service

        db_service = get_database_service()

        # 兼容测试：仅传 tool_id 时也视为可用（返回 200 success true）
        if action in (None, "", "view"):
            return _j({"success": True, "message": "数据库管理"}, 200)

        if action == "backup":
            result = db_service.backup_database()
            return _j(result)

        elif action == "restore":
            backup_file = params.get("backup_file")
            if not backup_file:
                return _j({"success": False, "message": "缺少参数：backup_file"}, 400)
            result = db_service.restore_database(backup_file)
            return _j(result)

        elif action == "list":
            result = db_service.list_backups()
            return _j(result)

        elif action == "delete":
            backup_file = params.get("backup_file")
            if not backup_file:
                return _j({"success": False, "message": "缺少参数：backup_file"}, 400)
            result = db_service.delete_backup(backup_file)
            return _j(result)

        else:
            return _j({"success": False, "message": f"未知的数据库操作：{action}"}, 400)
    elif tool_id == "system":
        from app.services import get_system_service

        system_service = get_system_service()

        # 兼容测试：仅传 tool_id 时也视为可用（返回 200 success true）
        if action in (None, "", "view"):
            return _j({"success": True, "message": "系统设置"}, 200)

        if action == "get_startup_config":
            result = system_service.get_startup_config()
            return _j({"success": True, "data": result})

        elif action == "enable_startup":
            result = system_service.enable_startup()
            return _j(result)

        elif action == "disable_startup":
            result = system_service.disable_startup()
            return _j(result)

        elif action == "get_system_info":
            result = system_service.get_system_info()
            return _j({"success": True, "data": result})

        elif action == "get_printer_config":
            result = system_service.get_printer_config()
            return _j(result)

        elif action == "set_default_printer":
            printer_name = params.get("printer_name")
            if not printer_name:
                return _j({"success": False, "message": "缺少参数：printer_name"}, 400)
            result = system_service.set_default_printer(printer_name)
            return _j(result)

        else:
            return _j({"success": False, "message": f"未知的系统操作：{action}"}, 400)
    elif tool_id == "upload_file":
        # upload_file 是“让用户上传文件”的 UI 引导工具。
        # 该接口本身不执行解析/入库，仅返回前端可触发上传浮层的提示文案。
        msg = "请上传文件以继续（Excel / 图片 / CSV 均可）。"
        return _j({"success": True, "message": msg}, 200)

    return NOT_HANDLED
