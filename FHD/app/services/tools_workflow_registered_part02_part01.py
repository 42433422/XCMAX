# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.services.tools_workflow_registered")


def _registered_router_mrp(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    from app.services.manufacturing_service import ManufacturingService

    svc = ManufacturingService()

    def _opt_int(value: _facade().Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    if action == "create_bom":
        return svc.create_bom(dict(params or {}))
    if action == "query_boms":
        return svc.query_boms(
            status=params.get("status"),
            product_id=_opt_int(params.get("product_id")),
            page=int(params.get("page") or 1),
            per_page=int(params.get("per_page") or 50),
        )
    if action == "get_bom":
        bom_id = int(params.get("bom_id") or params.get("id") or 0)
        if bom_id <= 0:
            return {"success": False, "message": "缺少 bom_id"}
        return svc.get_bom(bom_id)
    if action == "create_order":
        return svc.create_order(dict(params or {}))
    if action == "confirm_order":
        order_id = int(params.get("order_id") or 0)
        if order_id <= 0:
            return {"success": False, "message": "缺少 order_id"}
        return svc.confirm_order(order_id)
    if action == "consume":
        order_id = int(params.get("order_id") or 0)
        warehouse_id = int(params.get("warehouse_id") or 0)
        if order_id <= 0:
            return {"success": False, "message": "缺少 order_id"}
        return svc.consume(
            order_id=order_id, warehouse_id=warehouse_id, operator=params.get("operator")
        )
    if action == "finish":
        order_id = int(params.get("order_id") or 0)
        warehouse_id = int(params.get("warehouse_id") or 0)
        if order_id <= 0:
            return {"success": False, "message": "缺少 order_id"}
        return svc.finish(
            order_id=order_id, warehouse_id=warehouse_id, operator=params.get("operator")
        )
    if action == "query_orders":
        return svc.query_orders(
            status=params.get("status"),
            product_id=_opt_int(params.get("product_id")),
            page=int(params.get("page") or 1),
            per_page=int(params.get("per_page") or 50),
        )
    return {"success": False, "message": f"未注册的 mrp 动作: {action}"}


def _registered_router_suppliers(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    from app.application.facades.inventory_facade import PurchaseService

    svc = PurchaseService()
    if action in ("query", "query_suppliers", "list", "list_suppliers"):
        return svc.get_suppliers(
            status=params.get("status"),
            keyword=str(params.get("keyword") or params.get("search") or "").strip() or None,
        )
    if action == "get_supplier":
        supplier_id = int(params.get("supplier_id") or params.get("id") or 0)
        if supplier_id <= 0:
            return {"success": False, "message": "缺少 supplier_id"}
        result = svc.get_supplier(supplier_id)
        if isinstance(result, dict):
            return result
        return {"success": True, "data": result}
    return {"success": False, "message": f"未注册的 suppliers 动作: {action}"}


def _registered_router_shipment_records(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if str(runtime_context.get("service_source") or "") == "fastapi_shipment_records_route":
        from app.fastapi_routes import shipment_orders

        svc = shipment_orders._svc()
    else:
        from app.bootstrap import get_shipment_app_service

        svc = get_shipment_app_service()
    if action in ("list", "query"):
        unit = str(params.get("unit") or params.get("unit_name") or "").strip() or None
        return {"success": True, "data": svc.get_shipment_records(unit)}
    if action == "create":
        unit_name = str(params.get("unit_name") or params.get("purchase_unit") or "").strip()
        if not unit_name:
            return {"success": False, "message": "缺少 unit_name"}
        products = params.get("products") or params.get("items") or []
        if not isinstance(products, list):
            products = []
        return _facade().cast(
            "dict[Any, Any]",
            svc.create_shipment(
                unit_name=unit_name,
                items_data=products,
                contact_person=params.get("contact_person"),
                contact_phone=params.get("contact_phone"),
            ),
        )
    if action == "update":
        record_id = int(params.get("id") or 0)
        payload = {k: v for k, v in params.items() if k != "id"}
        return _facade().cast(
            "dict[Any, Any]", svc.update_shipment_record(record_id=record_id, **payload)
        )
    if action == "delete":
        return _facade().cast(
            "dict[Any, Any]", svc.delete_shipment_record(int(params.get("id") or 0))
        )
    if action == "export":
        return _facade().cast(
            "dict[Any, Any]",
            svc.export_shipment_records(
                unit_name=str(params.get("unit") or params.get("unit_name") or "").strip() or None,
                template_id=params.get("template_id"),
                status_filter=params.get("status"),
            ),
        )
    return {"success": False, "message": f"未注册的 shipment_records 动作: {action}"}


def _registered_router_shipment_orders(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if str(runtime_context.get("service_source") or "") == "fastapi_shipment_orders_route":
        from app.fastapi_routes import shipment_orders

        svc = shipment_orders._svc()
    else:
        from app.bootstrap import get_shipment_app_service

        svc = get_shipment_app_service()
    if action == "generate":
        unit_name = str(params.get("unit_name") or params.get("purchase_unit") or "").strip()
        products = params.get("products") or params.get("items") or []
        if not unit_name:
            return {"success": False, "message": "缺少 unit_name"}
        if not isinstance(products, list) or not products:
            return {"success": False, "message": "products 须为非空数组"}
        gen_kwargs: dict[str, _facade().Any] = {
            "unit_name": unit_name,
            "products": products,
            "date": params.get("date"),
        }
        if params.get("template_name"):
            gen_kwargs["template_name"] = params.get("template_name")
        elif params.get("template"):
            gen_kwargs["template_name"] = params.get("template")
        if params.get("template_id"):
            gen_kwargs["template_id"] = params.get("template_id")
        if params.get("preferred_template") or params.get("template"):
            gen_kwargs["preferred_template"] = params.get("preferred_template") or params.get(
                "template"
            )
        if params.get("order_number"):
            gen_kwargs["order_number"] = params.get("order_number")
        return _facade().cast("dict[Any, Any]", svc.generate_shipment_document(**gen_kwargs))
    if action == "generate_batch":
        shipments = params.get("shipments") or []
        if not isinstance(shipments, list) or not shipments:
            return {"success": False, "message": "shipments 不能为空"}
        ok_count = 0
        errors: list[dict[str, _facade().Any]] = []
        for idx, shipment in enumerate(shipments):
            if not isinstance(shipment, dict):
                errors.append({"index": idx, "error": "条目必须是对象"})
                continue
            unit_name = str(
                shipment.get("unit_name") or shipment.get("customer_name") or ""
            ).strip()
            products = shipment.get("products") or shipment.get("items") or []
            if not unit_name:
                errors.append({"index": idx, "error": "单位名称不能为空"})
                continue
            if not products:
                errors.append({"index": idx, "error": "产品列表不能为空"})
                continue
            try:
                batch_kwargs: dict[str, _facade().Any] = {
                    "unit_name": unit_name,
                    "products": products,
                    "date": shipment.get("date"),
                }
                if shipment.get("template_name"):
                    batch_kwargs["template_name"] = shipment.get("template_name")
                if shipment.get("template_id"):
                    batch_kwargs["template_id"] = shipment.get("template_id")
                result = svc.generate_shipment_document(**batch_kwargs)
                if result.get("success"):
                    ok_count += 1
                else:
                    errors.append({"index": idx, "error": result.get("message", "生成失败")})
            except _facade().RECOVERABLE_ERRORS as err:
                _facade().logger.exception("shipment_orders.generate_batch[%s]: %s", idx, err)
                errors.append({"index": idx, "error": str(err)})
        return {
            "success": ok_count > 0 or not errors,
            "data": {"processed": ok_count, "total": len(shipments), "errors": errors},
        }
    if action == "print":
        file_path = str(params.get("file_path") or "").strip()
        if not file_path:
            return {"success": False, "message": "文件路径不能为空"}
        order_id = params.get("order_id")
        if order_id:
            shipment_id = int(order_id)
            result = dict(
                svc.mark_as_printed(shipment_id, printer_name=str(params.get("printer_name") or ""))
            )
            result["file_path"] = file_path
            if "updated" not in result:
                result["updated"] = bool(result.get("success"))
            return result
        return {
            "success": True,
            "message": "发货单打印请求已完成，但未更新记录（缺少 order_id）",
            "printed_at": _facade().datetime.now().isoformat(),
            "file_path": file_path,
            "updated": False,
            "warning": "缺少 order_id，已跳过数据库状态更新",
        }
    if action == "clear_shipment":
        purchase_unit = str(params.get("purchase_unit") or params.get("unit_name") or "").strip()
        if not purchase_unit:
            return {"success": False, "message": "缺少购买单位参数"}
        result = dict(svc.clear_shipment_by_unit(purchase_unit) or {})
        result.setdefault("purchase_unit", purchase_unit)
        return result
    if action == "set_sequence":
        sequence = int(params.get("sequence", 1))
        result = dict(svc.set_order_sequence(sequence) or {})
        result.setdefault("sequence", sequence)
        return result
    if action == "reset_sequence":
        return dict(svc.reset_order_sequence() or {})
    if action == "clear_all":
        return dict(svc.clear_all_orders() or {})
    if action == "delete":
        shipment_id = int(
            params.get("id") or params.get("shipment_id") or params.get("order_id") or 0
        )
        result = dict(svc.delete_shipment(shipment_id) or {})
        result.setdefault("deleted_id", shipment_id)
        return result
    return {"success": False, "message": f"未注册的 shipment_orders 动作: {action}"}


def _registered_router_business_docking_family(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if action in ("view",):
        return {"success": True, "redirect": "/console?view=business-docking"}
    file_path = str(params.get("file_path") or "").strip()
    if not file_path:
        return {"success": False, "message": "缺少参数：file_path"}
    from app.services.document_templates_service import (
        _extract_excel_all_sheets_preview,
        _extract_excel_grid_preview,
        _extract_excel_grid_style_cache,
        _extract_structured_excel_preview,
        _list_excel_sheet_names,
    )

    if not _facade().os.path.exists(file_path):
        return {"success": False, "message": f"文件不存在：{file_path}"}
    sheet_name = str(params.get("sheet_name") or "").strip() or None
    structured = _extract_structured_excel_preview(file_path, sheet_name=sheet_name, sample_limit=8)
    grid_preview = _extract_excel_grid_preview(
        file_path, sheet_name=sheet_name, max_rows=24, max_cols=14
    )
    style_cache = _extract_excel_grid_style_cache(
        file_path, sheet_name=sheet_name, max_rows=24, max_cols=14
    )
    all_sheets = _extract_excel_all_sheets_preview(
        file_path, sample_limit=8, max_rows=24, max_cols=14
    )
    artifact: dict[str, _facade().Any] = {
        "artifact_type": "template_analysis",
        "name": _facade().os.path.basename(file_path) or "template-analysis",
        "source": f"{action}.template_extract",
        "uri": file_path,
        "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "summary": "Excel 模板结构分析结果",
        "fields": structured.get("fields") or [],
        "preview": {
            "sample_rows": structured.get("sample_rows") or [],
            "grid_preview": grid_preview,
            "sheet_names": _list_excel_sheet_names(file_path),
        },
        "metadata": {"parser_used": "template_extract", "sheet_name": sheet_name or ""},
    }
    return {
        "success": True,
        "file_path": file_path,
        "sheet_names": artifact["preview"]["sheet_names"],
        "fields": structured.get("fields") or [],
        "sample_rows": structured.get("sample_rows") or [],
        "grid_preview": grid_preview,
        "grid_style_cache": style_cache,
        "sheets": all_sheets,
        "artifacts": [artifact],
    }
