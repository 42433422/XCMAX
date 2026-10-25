"""Basic catalog and shipment-record legacy tool handlers."""

from __future__ import annotations

import logging
import os

from app.services.tools_payload_dispatch_common import NOT_HANDLED

logger = logging.getLogger(__name__)


def dispatch_basic_tool_payload(
    tool_id,
    action: str,
    params: dict,
    *,
    json_response_fn,
    hdr_getter,
    parse_order_text_fn,
):
    _j = json_response_fn
    _ = hdr_getter, parse_order_text_fn
    if tool_id == "products":
        effective_action = action
        if action in ("执行", "exec", "run", "execute"):
            effective_action = params.get("action", "view")

        keyword = (params.get("keyword") or "").strip()
        unit_name = (params.get("unit_name") or "").strip()
        model_number = (params.get("model_number") or "").strip()
        tin_spec = (params.get("tin_spec") or "").strip()

        search_verbs = ["search", "query", "find", "查找", "查询", "搜索"]
        is_search = (effective_action in search_verbs) or keyword

        if is_search and keyword:
            return _j(
                {
                    "success": True,
                    "redirect": f"/console?view=products&keyword={keyword}",
                    "message": f"已按关键词检索产品：{keyword}",
                    "data": {
                        "keyword": keyword,
                        "unit_name": unit_name,
                        "model_number": model_number,
                        "tin_spec": tin_spec,
                    },
                }
            )
        if effective_action == "view":
            return _j({"success": True, "redirect": "/console?view=products"})
        return _j({"success": True, "message": "产品管理"})

    if tool_id == "chat":
        return _j({"success": True, "redirect": "/console?view=chat", "message": "已打开智能对话"})

    elif tool_id == "ai_ecosystem":
        if action in ("list", "query"):
            return _j(
                {
                    "success": True,
                    "data": {
                        "views": ["ai-ecosystem"],
                        "integrations": ["deepseek", "bert", "rasa", "workflow-planner"],
                    },
                },
                200,
            )
        return _j(
            {"success": True, "redirect": "/console?view=ai-ecosystem", "message": "已打开AI生态"}
        )

    elif tool_id == "materials_list":
        if action in ("query", "list"):
            from app.application import get_material_application_service

            svc = get_material_application_service()
            result = svc.get_all_materials(
                search=str(params.get("search") or params.get("keyword") or "").strip(),
                category=str(params.get("category") or "").strip() or None,
                page=int(params.get("page") or 1),
                per_page=int(params.get("per_page") or 20),
            )
            return _j(result, 200)
        return _j(
            {
                "success": True,
                "redirect": "/console?view=materials-list",
                "message": "已打开原材料列表",
            }
        )

    elif tool_id == "business_docking":
        if action in ("extract", "preview", "analyze"):
            file_path = str(params.get("file_path") or "").strip()
            if not file_path:
                return _j(
                    {"success": False, "message": "缺少参数：file_path（Excel文件路径）"}, 400
                )
            from app.services.document_templates_service import (
                _extract_excel_grid_preview,
                _extract_structured_excel_preview,
                _list_excel_sheet_names,
            )

            if not os.path.exists(file_path):
                return _j({"success": False, "message": f"文件不存在：{file_path}"}, 404)
            sheet_name = str(params.get("sheet_name") or "").strip() or None
            return _j(
                {
                    "success": True,
                    "file_path": file_path,
                    "sheet_names": _list_excel_sheet_names(file_path),
                    "structured": _extract_structured_excel_preview(
                        file_path, sheet_name=sheet_name, sample_limit=8
                    ),
                    "grid_preview": _extract_excel_grid_preview(
                        file_path, sheet_name=sheet_name, max_rows=24, max_cols=14
                    ),
                },
                200,
            )
        return _j(
            {
                "success": True,
                "redirect": "/console?view=business-docking",
                "message": "已打开业务对接",
            }
        )

    elif tool_id == "shipment_records":
        from app.bootstrap import get_shipment_app_service

        shipment_svc = get_shipment_app_service()
        if action in ("list", "query"):
            unit = str(params.get("unit") or params.get("unit_name") or "").strip() or None
            return _j({"success": True, "data": shipment_svc.get_shipment_records(unit)}, 200)
        if action == "update":
            record_id = int(params.get("id") or 0)
            payload = {k: v for k, v in params.items() if k != "id"}
            return _j(shipment_svc.update_shipment_record(record_id=record_id, **payload), 200)
        if action == "delete":
            return _j(shipment_svc.delete_shipment_record(int(params.get("id") or 0)), 200)
        if action == "export":
            result = shipment_svc.export_shipment_records(
                unit_name=str(params.get("unit") or params.get("unit_name") or "").strip() or None,
                template_id=params.get("template_id"),
                status_filter=params.get("status"),
            )
            return _j(result, 200)
        return _j(
            {
                "success": True,
                "redirect": "/console?view=shipment-records",
                "message": "已打开出货记录",
            }
        )

    return NOT_HANDLED
