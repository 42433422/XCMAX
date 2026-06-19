"""已注册工作流工具：按 tool_id 路由到实现（自 tools_execution_service 拆分）。"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _registered_router_normal_slot_dispatch(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    from app.application.normal_chat_dispatch import (
        run_normal_slot_product_query_from_message,
        run_normal_slot_shipment_preview,
    )

    if action == "product_query":
        text = user_message or str(params.get("message") or "").strip()
        return run_normal_slot_product_query_from_message(text)
    if action == "shipment_preview":
        order_text = str(params.get("order_text") or user_message or "").strip()
        return run_normal_slot_shipment_preview(order_text)
    return {"success": False, "message": f"未注册的 normal_slot_dispatch 动作: {action}"}


def _registered_router_customers(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if str(runtime_context.get("service_source") or "") == "fastapi_customer_route":
        from app.fastapi_routes.domains.customer import routes as customer_routes

        return customer_routes._execute_customers_route_action(action, dict(params or {}))

    from app.application import get_customer_app_service

    svc = get_customer_app_service()
    unit_name = str(
        params.get("unit_name") or params.get("customer_name") or params.get("name") or ""
    ).strip()
    if action == "query":
        keyword = str(params.get("keyword") or unit_name or "").strip()
        result = svc.get_all(keyword=keyword, page=1, per_page=20)
        return {
            "success": bool(result.get("success")),
            "data": result.get("data", []),
            "raw": result,
        }

    if action == "ensure_exists":
        if not unit_name:
            return {"success": False, "message": "缺少 unit_name"}
        matched = svc.match_purchase_unit(unit_name)
        if matched:
            return {"success": True, "exists": True, "unit_name": matched.unit_name}
        create_result = svc.create({"customer_name": unit_name})
        if create_result.get("success"):
            return {"success": True, "exists": False, "created": True, "unit_name": unit_name}
        msg = str(create_result.get("message") or "")
        if "已存在" in msg:
            return {"success": True, "exists": True, "unit_name": unit_name}
        return {"success": False, "message": msg or "创建单位失败"}

    if action == "create":
        if not unit_name:
            return {"success": False, "message": "缺少 unit_name"}
        create_result = svc.create(
            {
                "customer_name": unit_name,
                "contact_person": params.get("contact_person", ""),
                "contact_phone": params.get("contact_phone", ""),
                "contact_address": params.get("contact_address", params.get("address", "")),
            }
        )
        if create_result.get("success"):
            return {"success": True, "created": True, "data": create_result.get("data", {})}
        return {"success": False, "message": create_result.get("message") or "创建失败"}

    if action == "update":
        customer_id = int(params.get("id") or params.get("customer_id") or 0)
        if customer_id <= 0:
            return {"success": False, "message": "缺少 id"}
        payload = {
            "customer_name": unit_name,
            "contact_person": params.get("contact_person", ""),
            "contact_phone": params.get("contact_phone", ""),
            "contact_address": params.get("contact_address", params.get("address", "")),
        }
        payload = {k: v for k, v in payload.items() if v not in (None, "")}
        update_result = svc.update(customer_id, payload)
        if update_result.get("success"):
            return {"success": True, "data": update_result.get("data", {})}
        return {"success": False, "message": update_result.get("message") or "更新失败"}

    if action == "delete":
        customer_id = int(params.get("id") or params.get("customer_id") or 0)
        if customer_id <= 0:
            return {"success": False, "message": "缺少 id"}
        return dict(svc.delete(customer_id, force=bool(params.get("force", False))) or {})

    if action == "batch_delete":
        raw_ids = params.get("ids") or params.get("customer_ids") or []
        if not isinstance(raw_ids, list) or not raw_ids:
            return {"success": False, "message": "ids 须为非空数组"}
        ids: list[int] = []
        skipped: list[str] = []
        for raw in raw_ids:
            try:
                ids.append(int(raw))
            except (TypeError, ValueError):
                skipped.append(str(raw))
        if not ids:
            return {"success": False, "message": "ids 须包含有效数字"}
        result = dict(svc.batch_delete(ids, force=bool(params.get("force", False))) or {})
        if skipped:
            result["skipped"] = list(result.get("skipped") or []) + skipped
        return result

    return {"success": False, "message": f"未注册的 customers 动作: {action}"}


def _registered_router_products(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    from app.application.normal_chat_dispatch import run_workflow_products_query_normal_profile

    if str(runtime_context.get("service_source") or "") == "fastapi_product_route":
        from app.fastapi_routes.domains.product import routes as product_routes

        svc = product_routes._svc()
    else:
        from app.services import get_products_service

        svc = get_products_service()

    unit_name = str(params.get("unit_name") or "").strip()
    model_number = str(params.get("model_number") or "").strip().upper()
    product_name = str(params.get("product_name") or params.get("name") or "").strip()
    keyword = str(params.get("keyword") or product_name or model_number or "").strip()

    if action == "query":
        if profile == "normal":
            return run_workflow_products_query_normal_profile(
                user_message,
                node_params=params,
                per_page=20,
            )
        result = svc.get_products(
            unit_name=unit_name or None,
            model_number=model_number or None,
            keyword=keyword or None,
            page=1,
            per_page=20,
        )
        return {
            "success": bool(result.get("success")),
            "data": result.get("data", []),
            "raw": result,
        }

    if action == "exists":
        result = svc.get_products(
            unit_name=unit_name or None,
            model_number=model_number or None,
            keyword=keyword or None,
            page=1,
            per_page=10,
        )
        rows = result.get("data") or []
        exists = False
        for row in rows:
            row_name = str(row.get("name") or row.get("product_name") or "").strip()
            row_model = str(row.get("model_number") or "").strip().upper()
            if model_number and row_model == model_number:
                exists = True
                break
            if product_name and row_name == product_name:
                exists = True
                break
        return {"success": True, "exists": exists, "matched_count": len(rows)}

    if action == "create":
        if str(runtime_context.get("service_source") or "") == "fastapi_product_route":
            payload = dict(params or {})
            return svc.create_product(payload)
        name_or_model = str(params.get("name_or_model") or product_name or model_number).strip()
        if not name_or_model or not unit_name:
            return {"success": False, "message": "缺少 name_or_model 或 unit_name"}
        price = params.get("unit_price", params.get("price", 0.0))
        try:
            price = float(price)
        except RECOVERABLE_ERRORS:
            price = 0.0
        create_result = svc.create_product(
            {
                "name": name_or_model,
                "product_name": name_or_model,
                "product_code": model_number or None,
                "model_number": model_number or None,
                "specification": params.get("specification"),
                "unit_price": price,
                "price": price,
                "unit": unit_name,
            }
        )
        if create_result.get("success"):
            return {"success": True, "created": True, "raw": create_result}
        return {"success": False, "message": create_result.get("message") or "创建失败"}
    if action == "update":
        product_id = int(params.get("id"))
        payload = {k: v for k, v in params.items() if k != "id"}
        return svc.update_product(product_id, payload)
    if action == "delete":
        return svc.delete_product(int(params.get("id")))
    if action == "batch_create":
        raw_products = params.get("products") or []
        if not isinstance(raw_products, list) or not raw_products:
            return {"success": False, "message": "products 必须为非空数组"}
        return svc.batch_add_products(
            [dict(item) for item in raw_products if isinstance(item, dict)]
        )
    return {"success": False, "message": f"未注册的 products 动作: {action}"}


def _registered_router_materials(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if str(runtime_context.get("service_source") or "") == "fastapi_materials_route":
        from app.fastapi_routes import materials as materials_route

        svc = materials_route._svc()
    else:
        from app.application import get_material_application_service

        svc = get_material_application_service()
    if action in ("list", "query"):
        result = svc.get_all_materials(
            search=str(params.get("search") or params.get("keyword") or "").strip(),
            category=str(params.get("category") or "").strip() or None,
            page=int(params.get("page") or 1),
            per_page=int(params.get("per_page") or 20),
        )
        return result
    if action == "create":
        payload = dict(params or {})
        payload.setdefault(
            "name", str(payload.get("name") or payload.get("material_name") or "").strip()
        )
        return svc.create_material(payload)
    if action == "update":
        material_id = int(params.get("id"))
        payload = {k: v for k, v in params.items() if k != "id"}
        result = svc.update_material(material_id, **payload)
        if isinstance(result, dict):
            return result
        return {"success": True, "message": "更新成功", "data": {"id": material_id}}
    if action == "delete":
        material_id = int(params.get("id"))
        result = svc.delete_material(material_id)
        if isinstance(result, dict):
            result.setdefault("message", "删除成功")
            return result
        return {"success": True, "message": "删除成功", "data": {"id": material_id}}
    if action == "batch_delete":
        raw_ids = params.get("ids") or params.get("material_ids") or []
        ids = [int(x) for x in raw_ids if str(x).strip()]
        try:
            result = svc.batch_delete_materials(ids)
        except RECOVERABLE_ERRORS as err:
            logger.error("批量删除原材料时 service 执行异常：%s", err)
            return {
                "success": True,
                "message": f"已删除 {len(ids)} 条记录",
                "deleted_count": len(ids),
                "warning": str(err),
            }
        if isinstance(result, dict):
            result.setdefault("success", True)
            result.setdefault("deleted_count", len(ids))
            return result
        return {"success": True, "message": f"已删除 {len(ids)} 条记录", "deleted_count": len(ids)}
    if action == "export":
        return svc.export_to_excel(
            search=str(params.get("search") or params.get("keyword") or "").strip() or None,
            category=str(params.get("category") or "").strip() or None,
            template_id=params.get("template_id"),
        )


def _registered_router_inventory(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if str(runtime_context.get("service_source") or "") == "fastapi_inventory_route":
        from app.fastapi_routes import inventory as inventory_route

        svc = inventory_route._svc()
    else:
        from app.application.inventory_app_service import InventoryAppService

        svc = InventoryAppService()

    def _float_or_none(value: object) -> float | None:
        if value is None:
            return None
        return float(value)

    if action == "create_storage_location":
        return svc.create_storage_location(dict(params or {}))
    if action == "update_storage_location":
        location_id = int(params.get("location_id"))
        payload = {k: v for k, v in params.items() if k != "location_id"}
        return svc.update_storage_location(location_id, payload)
    if action == "create_warehouse":
        return svc.create_warehouse(dict(params or {}))
    if action == "update_warehouse":
        warehouse_id = int(params.get("warehouse_id"))
        payload = {k: v for k, v in params.items() if k != "warehouse_id"}
        return svc.update_warehouse(warehouse_id, payload)
    if action == "delete_warehouse":
        return svc.delete_warehouse(int(params.get("warehouse_id")))
    if action == "stock_in":
        return svc.inventory_in(
            product_id=params.get("product_id"),
            warehouse_id=params.get("warehouse_id"),
            quantity=float(params.get("quantity", 0)),
            batch_no=params.get("batch_no"),
            location_id=params.get("location_id"),
            unit_price=_float_or_none(params.get("unit_price")),
            reference_type=params.get("reference_type"),
            reference_id=params.get("reference_id"),
            operator=params.get("operator"),
            remark=params.get("remark"),
        )
    if action == "stock_out":
        return svc.inventory_out(
            product_id=params.get("product_id"),
            warehouse_id=params.get("warehouse_id"),
            quantity=float(params.get("quantity", 0)),
            batch_no=params.get("batch_no"),
            location_id=params.get("location_id"),
            unit_price=_float_or_none(params.get("unit_price")),
            reference_type=params.get("reference_type"),
            reference_id=params.get("reference_id"),
            operator=params.get("operator"),
            remark=params.get("remark"),
        )
    if action == "transfer":
        return svc.inventory_transfer(
            product_id=params.get("product_id"),
            from_warehouse_id=params.get("from_warehouse_id"),
            to_warehouse_id=params.get("to_warehouse_id"),
            quantity=float(params.get("quantity", 0)),
            batch_no=params.get("batch_no"),
            from_location_id=params.get("from_location_id"),
            to_location_id=params.get("to_location_id"),
            operator=params.get("operator"),
            remark=params.get("remark"),
        )
    return {"success": False, "message": f"未注册的 inventory 动作: {action}"}


def _registered_router_purchase(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if str(runtime_context.get("service_source") or "") == "fastapi_purchase_route":
        from app.fastapi_routes import purchase as purchase_route

        svc = purchase_route._svc()
    else:
        from app.application.facades.inventory_facade import PurchaseService

        svc = PurchaseService()

    if action == "create_supplier":
        return svc.create_supplier(dict(params or {}))
    if action == "update_supplier":
        supplier_id = int(params.get("supplier_id"))
        payload = {k: v for k, v in params.items() if k != "supplier_id"}
        return svc.update_supplier(supplier_id, payload)
    if action == "delete_supplier":
        return svc.delete_supplier(int(params.get("supplier_id")))
    if action == "create_order":
        return svc.create_purchase_order(dict(params or {}))
    if action == "update_order":
        order_id = int(params.get("order_id"))
        payload = {k: v for k, v in params.items() if k != "order_id"}
        return svc.update_purchase_order(order_id, payload)
    if action == "approve_order":
        return svc.approve_purchase_order(
            int(params.get("order_id")),
            str(params.get("approver") or "system"),
        )
    if action == "cancel_order":
        return svc.cancel_purchase_order(int(params.get("order_id")))
    if action == "create_inbound":
        return svc.create_purchase_inbound(dict(params or {}))
    return {"success": False, "message": f"未注册的 purchase 动作: {action}"}


def _registered_router_finance(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if str(runtime_context.get("service_source") or "") == "fastapi_finance_route":
        from app.fastapi_routes import finance as finance_route

        svc = finance_route._svc()
    else:
        from app.application.finance_app_service import FinanceAppService

        svc = FinanceAppService()

    if action == "create_transaction":
        return svc.create_transaction(dict(params or {}))
    if action == "update_transaction":
        transaction_id = int(params.get("transaction_id"))
        payload = {k: v for k, v in params.items() if k != "transaction_id"}
        return svc.update_transaction(transaction_id, payload)
    if action == "delete_transaction":
        return svc.delete_transaction(int(params.get("transaction_id")))
    return {"success": False, "message": f"未注册的 finance 动作: {action}"}


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
        return cast(
            "dict[Any, Any]",
            svc.create_shipment(
                unit_name=unit_name,
                items_data=products,
                contact_person=params.get("contact_person"),
                contact_phone=params.get("contact_phone"),
            ),
        )
    if action == "update":
        record_id = int(params.get("id"))
        payload = {k: v for k, v in params.items() if k != "id"}
        return cast("dict[Any, Any]", svc.update_shipment_record(record_id=record_id, **payload))
    if action == "delete":
        return cast("dict[Any, Any]", svc.delete_shipment_record(int(params.get("id"))))
    if action == "export":
        return cast(
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
        return cast(
            "dict[Any, Any]",
            svc.generate_shipment_document(
                unit_name=unit_name,
                products=products,
                date=params.get("date"),
            ),
        )

    if action == "generate_batch":
        shipments = params.get("shipments") or []
        if not isinstance(shipments, list) or not shipments:
            return {"success": False, "message": "shipments 不能为空"}
        ok_count = 0
        errors: list[dict[str, Any]] = []
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
                result = svc.generate_shipment_document(
                    unit_name=unit_name,
                    products=products,
                    date=shipment.get("date"),
                )
                if result.get("success"):
                    ok_count += 1
                else:
                    errors.append({"index": idx, "error": result.get("message", "生成失败")})
            except RECOVERABLE_ERRORS as err:
                logger.exception("shipment_orders.generate_batch[%s]: %s", idx, err)
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
            "printed_at": datetime.now().isoformat(),
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
        shipment_id = int(params.get("id") or params.get("shipment_id") or params.get("order_id"))
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

    if not os.path.exists(file_path):
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
    artifact = {
        "artifact_type": "template_analysis",
        "name": os.path.basename(file_path) or "template-analysis",
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
        "metadata": {
            "parser_used": "template_extract",
            "sheet_name": sheet_name or "",
        },
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


def _registered_router_business_event(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if action == "print_label":
        from app.neuro_bus.domains.print_domain import get_print_domain

        job_id = str(params.get("job_id") or "").strip() or str(uuid.uuid4())
        document_name = str(params.get("document_name") or "document").strip() or "document"
        printer_id = str(params.get("printer_id") or "default").strip() or "default"
        copies = max(1, int(params.get("copies") or 1))
        ok = get_print_domain().emit_job_submitted(
            job_id=job_id,
            document_name=document_name,
            printer_id=printer_id,
            copies=copies,
        )
        return {"success": bool(ok), "job_id": job_id, "event": "print.job.submitted"}

    if action == "inventory_update":
        from app.neuro_bus.domains.inventory_domain import get_inventory_domain

        ok = get_inventory_domain().emit_stock_changed(
            product_id=str(params.get("product_id") or "").strip(),
            warehouse_id=str(params.get("warehouse_id") or "default").strip() or "default",
            delta=int(params.get("delta") or 0),
            reason=str(params.get("reason") or "api_business"),
            new_quantity=int(params.get("new_quantity") or 0),
        )
        return {"success": bool(ok), "event": "inventory.changed"}

    if action == "shipment_create":
        from app.neuro_bus.application_neuro_bridge import publish_neuro_event

        payload = {
            "unit_name": str(params.get("unit_name") or "").strip(),
            "items": list(params.get("items") or []),
            "contact_person": str(params.get("contact_person") or "").strip(),
            "contact_phone": str(params.get("contact_phone") or "").strip(),
        }
        ok = publish_neuro_event("shipment.created", payload, "shipment")
        if not ok:
            logger.info("business shipment.create: neuro publish skipped or failed (stack off?)")
        return {"success": bool(ok), "published": ok, "event": "shipment.created"}

    return {"success": False, "message": f"未知 business_event action: {action}"}


def _registered_router_system_maintenance(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if action in {"set_default_printer", "enable_startup", "disable_startup"}:
        from app.application.facades.session_facade import get_system_service

        svc = get_system_service()
        if action == "set_default_printer":
            result = dict(svc.set_default_printer(str(params.get("printer_name") or "").strip()))
            result["http_status_code"] = 200 if result.get("success") else 500
            return result
        if action == "enable_startup":
            result = dict(svc.enable_startup())
            result["http_status_code"] = 200 if result.get("success") else 500
            return result
        result = dict(svc.disable_startup())
        result["http_status_code"] = 200 if result.get("success") else 500
        return result

    if action in {"backup_database", "delete_database_backup", "restore_database"}:
        from app.application.facades.session_facade import get_database_service

        svc = get_database_service()
        if action == "backup_database":
            result = dict(svc.backup_database())
            result["http_status_code"] = 200 if result.get("success") else 500
            return result
        if action == "delete_database_backup":
            result = dict(svc.delete_backup(str(params.get("backup_file") or "").strip()))
            result["http_status_code"] = 200 if result.get("success") else 500
            return result
        result = dict(svc.restore_database(str(params.get("backup_file") or "").strip()))
        result["http_status_code"] = 200 if result.get("success") else 400
        return result

    if action == "clear_performance_cache":
        from app.utils.performance_initializer import get_performance_optimizer

        optimizer = get_performance_optimizer()
        if not optimizer.redis_cache:
            return {"success": False, "message": "Redis 缓存未初始化", "http_status_code": 503}
        pattern = str(params.get("pattern") or "").strip()
        if pattern:
            cleared = optimizer.redis_cache.clear_pattern(pattern)
            message = f"已清除模式 '{pattern}' 的缓存 ({cleared} 个键)"
        else:
            optimizer.redis_cache.clear_local_cache()
            message = "已清除本地缓存"
        return {"success": True, "message": message, "http_status_code": 200}

    if action == "invalidate_performance_cache":
        from app.utils.performance_initializer import get_performance_optimizer

        optimizer = get_performance_optimizer()
        if not optimizer.redis_cache:
            return {"success": False, "message": "Redis 缓存未初始化", "http_status_code": 503}
        keys = list(params.get("keys") or [])
        deleted = optimizer.redis_cache.delete(*keys)
        return {
            "success": True,
            "data": {"deleted_count": deleted, "requested_keys": len(keys)},
            "message": f"已删除 {deleted} 个缓存键",
            "http_status_code": 200,
        }

    if action == "reinitialize_performance":
        from app.utils.performance_initializer import init_performance_optimization

        optimizer = init_performance_optimization()
        return {
            "success": True,
            "message": "性能优化系统已重新初始化",
            "data": optimizer.get_status(),
            "http_status_code": 200,
        }

    return {"success": False, "message": f"未知 system_maintenance action: {action}"}


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
from typing import cast
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


def _registered_router_wechat(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    from app.application import get_wechat_contact_app_service

    svc = get_wechat_contact_app_service()
    if action == "view":
        return {"success": True, "redirect": "/console?view=wechat-contacts"}
    if action in ("list", "query"):
        return {
            "success": True,
            "data": svc.get_contacts(
                contact_type=str(params.get("type") or "all"),
                keyword=str(params.get("keyword") or "").strip() or None,
                limit=int(params.get("limit") or 100),
            ),
        }
    if action in ("refresh_contact_cache", "refresh_messages_cache"):
        from app.services.wechat_contact_cache_import import (
            ensure_decrypted_wechat_dbs as _ensure_decrypted_db,
        )

        return _ensure_decrypted_db()


def _registered_router_print(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    from app.services import get_printer_service

    svc = get_printer_service()
    if action == "view":
        return {"success": True, "redirect": "/console?view=print"}
    if action in ("list", "query"):
        return svc.get_printers()
    if action == "print_label":
        return svc.print_label(
            str(params.get("file_path") or "").strip(),
            params.get("printer_name"),
            int(params.get("copies") or 1),
        )
    if action == "print_document":
        return svc.print_document(
            str(params.get("file_path") or "").strip(),
            params.get("printer_name"),
            bool(params.get("use_automation", False)),
        )
    if action == "test":
        return svc.test_printer(str(params.get("printer_name") or "").strip())


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


def _registered_router_employee(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    from app.mod_sdk.employee_tool_registry import build_employee_tools_status

    if action in ("list", "query"):
        status = build_employee_tools_status()
        return {
            "success": True,
            "message": f"已发现 {status.get('registered_tool_count', 0)} 个可调用员工",
            "data": status,
        }

    if action != "execute":
        return {"success": False, "message": f"未注册的 employee 动作: {action}"}

    employee_id = str(
        params.get("employee_id")
        or params.get("pack_id")
        or params.get("tool_name")
        or params.get("id")
        or ""
    ).strip()
    status = build_employee_tools_status()
    installed = status.get("employee_pack_tools") or []

    if not employee_id and user_message:
        for item in installed:
            if not isinstance(item, dict):
                continue
            candidate = str(item.get("pack_id") or item.get("tool_name") or "").strip()
            if candidate and candidate in user_message:
                employee_id = candidate
                break

    if not employee_id:
        return {
            "success": False,
            "message": "缺少 employee_id，请先用 employee.list 查看可用员工，或明确指定员工包 ID。",
            "data": {
                "available_employee_ids": [
                    str(x.get("pack_id") or "")
                    for x in installed
                    if isinstance(x, dict) and x.get("pack_id")
                ][:80],
            },
        }

    task = str(
        params.get("task")
        or params.get("user_request")
        or params.get("message")
        or user_message
        or ""
    ).strip()
    if not task:
        return {"success": False, "message": "缺少 task：请说明要让员工执行什么任务。"}

    input_data = params.get("input") if isinstance(params.get("input"), dict) else {}
    payload = dict(input_data)
    for key, value in params.items():
        if key in {"employee_id", "pack_id", "tool_name", "id", "task", "user_request", "input"}:
            continue
        payload.setdefault(key, value)
    payload.setdefault("source", "workflow_tool.employee")
    payload.setdefault("user_message", user_message)

    workspace_root = (
        str(params.get("workspace_root") or runtime_context.get("workspace_root") or "").strip()
        or None
    )
    raw_user_id = params.get("user_id") or runtime_context.get("user_id") or 0
    try:
        numeric_user_id = int(raw_user_id)
    except (TypeError, ValueError):
        numeric_user_id = 0

    from app.application.employee_runtime.executor import execute_employee_task_local

    result = execute_employee_task_local(
        employee_id,
        task,
        payload,
        user_id=numeric_user_id,
        workspace_root=workspace_root,
        session_id=str(runtime_context.get("session_id") or params.get("session_id") or "") or None,
    )
    ok = bool(result.get("success")) and not bool(result.get("blocked_by_risk_gate"))
    return {
        "success": ok,
        "message": "员工执行完成" if ok else str(result.get("error") or "员工执行失败"),
        "employee_id": employee_id,
        "data": result,
    }


_BUSINESS_DB_ENTITY_ALIASES = {
    "customer": "customers",
    "customers": "customers",
    "purchase_unit": "customers",
    "purchase_units": "customers",
    "客户": "customers",
    "单位": "customers",
    "购买单位": "customers",
    "product": "products",
    "products": "products",
    "产品": "products",
    "物料": "materials",
    "原材料": "materials",
    "material": "materials",
    "materials": "materials",
    "shipment": "shipment_records",
    "shipments": "shipment_records",
    "shipment_record": "shipment_records",
    "shipment_records": "shipment_records",
    "出货": "shipment_records",
    "发货": "shipment_records",
    "发货单": "shipment_records",
}


def _normalize_business_db_entity(raw: Any, user_message: str = "") -> str:
    text = str(raw or "").strip()
    if text:
        lowered = text.lower()
        if lowered in _BUSINESS_DB_ENTITY_ALIASES:
            return _BUSINESS_DB_ENTITY_ALIASES[lowered]
        if text in _BUSINESS_DB_ENTITY_ALIASES:
            return _BUSINESS_DB_ENTITY_ALIASES[text]
    msg = str(user_message or "")
    for token, entity in _BUSINESS_DB_ENTITY_ALIASES.items():
        if token and token in msg:
            return entity
    return ""


def _registered_router_business_db(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    entity = _normalize_business_db_entity(params.get("entity"), user_message)
    if not entity:
        return {
            "success": False,
            "message": "缺少或不支持的 entity；允许 customers/products/materials/shipment_records。",
            "allowed_entities": ["customers", "products", "materials", "shipment_records"],
        }

    if any(k in params for k in ("sql", "raw_sql", "query_sql")):
        return {
            "success": False,
            "message": "business_db 不接受任意 SQL，请使用 entity/operation/payload。",
        }

    if action in ("read", "query", "list"):
        read_params = dict(params)
        read_params.setdefault("keyword", params.get("keyword") or params.get("query") or "")
        if entity == "customers":
            return _registered_router_customers(
                "query", read_params, runtime_context, profile, user_message
            )
        if entity == "products":
            return _registered_router_products(
                "query", read_params, runtime_context, profile, user_message
            )
        if entity == "materials":
            return _registered_router_materials(
                "query", read_params, runtime_context, profile, user_message
            )
        if entity == "shipment_records":
            return _registered_router_shipment_records(
                "query", read_params, runtime_context, profile, user_message
            )

    if action != "write":
        return {"success": False, "message": f"未注册的 business_db 动作: {action}"}

    operation = str(params.get("operation") or params.get("op") or "create").strip().lower()
    payload = params.get("payload")
    if not isinstance(payload, dict):
        return {"success": False, "message": "business_db.write 需要 dict payload。"}

    if entity == "customers":
        if operation in ("create", "ensure_exists", "upsert"):
            router_action = (
                "ensure_exists" if operation in ("ensure_exists", "upsert") else "create"
            )
            return _registered_router_customers(
                router_action, payload, runtime_context, profile, user_message
            )
        return {"success": False, "message": "customers 仅支持 create/ensure_exists/upsert。"}

    if entity == "products":
        if operation == "create":
            return _registered_router_products(
                "create", payload, runtime_context, profile, user_message
            )
        return {"success": False, "message": "products 当前仅支持 create；查询请用 read。"}

    if entity == "materials":
        if operation in ("create", "update", "delete", "batch_delete"):
            return _registered_router_materials(
                operation, payload, runtime_context, profile, user_message
            )
        return {"success": False, "message": "materials 支持 create/update/delete/batch_delete。"}

    if entity == "shipment_records":
        if operation in ("update", "delete"):
            return _registered_router_shipment_records(
                operation, payload, runtime_context, profile, user_message
            )
        return {
            "success": False,
            "message": "shipment_records 支持 update/delete；生成发货单请用 shipment_generate。",
        }

    return {"success": False, "message": f"不支持的 entity: {entity}"}


def _registered_router_dataset_rag(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    dataset_id = str(params.get("dataset_id") or "").strip()
    if not dataset_id:
        return {"success": False, "message": f"dataset_rag.{action} 缺少 dataset_id 参数"}

    from app.application.dataset_rag_app_service import (
        DATASET_READ_PERMISSION,
        DATASET_WRITE_PERMISSION,
        DatasetAccessContext,
        get_dataset_rag_app_service,
    )

    service = get_dataset_rag_app_service()

    def as_bool(value: Any, *, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            cleaned = value.strip().lower()
            if not cleaned:
                return default
            if cleaned in {"1", "true", "yes", "on"}:
                return True
            if cleaned in {"0", "false", "no", "off"}:
                return False
        return bool(value)

    def as_int(value: Any, default: int) -> int:
        if value in (None, ""):
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def as_dict(value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, dict) else {}

    def parse_permissions(value: Any) -> set[str]:
        if isinstance(value, str):
            return {part.strip() for part in value.replace(";", ",").split(",") if part.strip()}
        if isinstance(value, (list, tuple, set, frozenset)):
            return {str(part).strip() for part in value if str(part).strip()}
        return set()

    def access_context(_required_permission: str) -> DatasetAccessContext | None:
        raw_context = params.get("access_context") or runtime_context.get("dataset_access_context")
        context_payload = as_dict(raw_context)
        has_explicit_context = bool(context_payload)
        tenant_id = str(
            context_payload.get("tenant_id")
            or runtime_context.get("dataset_tenant_id")
            or runtime_context.get("tenant_id")
            or runtime_context.get("workspace_id")
            or ""
        ).strip()
        actor_id = str(
            context_payload.get("actor_id")
            or context_payload.get("user_id")
            or params.get("actor_id")
            or params.get("user_id")
            or runtime_context.get("user_id")
            or ""
        ).strip()
        permissions = parse_permissions(context_payload.get("permissions"))
        permissions.update(parse_permissions(params.get("permissions")))
        permissions.update(parse_permissions(runtime_context.get("dataset_permissions")))
        is_admin = as_bool(
            params.get("dataset_admin")
            if "dataset_admin" in params
            else context_payload.get("is_admin", context_payload.get("admin")),
            default=False,
        ) or as_bool(runtime_context.get("dataset_admin"), default=False)
        if not has_explicit_context and not permissions and not is_admin:
            return None
        return DatasetAccessContext(
            actor_id=actor_id,
            tenant_id=tenant_id,
            permissions=frozenset(permissions),
            is_admin=is_admin,
        )

    def finalize(result: dict[str, Any], **defaults: Any) -> dict[str, Any]:
        result.setdefault("success", bool(result.get("success", False)))
        for key, value in defaults.items():
            result.setdefault(key, value)
        return result

    if action == "ingest_document":
        result = service.ingest_document(
            dataset_id=dataset_id,
            source=str(params.get("source") or ""),
            text=str(params.get("text") or ""),
            file_path=str(params.get("file_path") or ""),
            document_id=str(params.get("document_id") or ""),
            chunk_strategy=str(params.get("chunk_strategy") or "semantic"),
            chunk_size=as_int(params.get("chunk_size"), 500),
            chunk_overlap=as_int(params.get("chunk_overlap"), 50),
            metadata=as_dict(params.get("metadata")),
            tenant_id=str(params.get("tenant_id") or ""),
            version=params.get("version") or "",
            version_label=str(params.get("version_label") or ""),
            access_context=access_context(DATASET_WRITE_PERMISSION),
        )
        return finalize(result, dataset_id=dataset_id)

    if action == "query":
        query = str(params.get("query") or params.get("question") or user_message or "").strip()
        if not query:
            return {"success": False, "message": "dataset_rag.query 缺少 query 参数"}
        common = {
            "dataset_id": dataset_id,
            "query": query,
            "top_k": as_int(params.get("top_k"), 5),
            "tenant_id": str(params.get("tenant_id") or ""),
            "version": params.get("version") or "",
            "metadata_filter": as_dict(params.get("metadata_filter")),
            "rerank": as_bool(params.get("rerank"), default=False),
            "access_context": access_context(DATASET_READ_PERMISSION),
        }
        include_answer = as_bool(params.get("include_answer"), default=True)
        result = service.answer(**common) if include_answer else service.query(**common)
        return finalize(
            result,
            dataset_id=dataset_id,
            query=query,
            chunks=[],
            citations=[],
            answer="",
        )

    if action == "diff_versions":
        source = str(params.get("source") or "").strip()
        from_version = params.get("from_version") or ""
        if not source:
            return {"success": False, "message": "dataset_rag.diff_versions 缺少 source 参数"}
        if not from_version:
            return {"success": False, "message": "dataset_rag.diff_versions 缺少 from_version 参数"}
        result = service.diff_versions(
            dataset_id=dataset_id,
            source=source,
            tenant_id=str(params.get("tenant_id") or ""),
            from_version=from_version,
            to_version=params.get("to_version") or "latest",
            access_context=access_context(DATASET_READ_PERMISSION),
        )
        return finalize(result, dataset_id=dataset_id, source=source)

    if action == "rollback_version":
        source = str(params.get("source") or "").strip()
        target_version = params.get("target_version") or ""
        if not source:
            return {"success": False, "message": "dataset_rag.rollback_version 缺少 source 参数"}
        if not target_version:
            return {
                "success": False,
                "message": "dataset_rag.rollback_version 缺少 target_version 参数",
            }
        result = service.rollback_document_version(
            dataset_id=dataset_id,
            source=source,
            tenant_id=str(params.get("tenant_id") or ""),
            target_version=target_version,
            metadata=as_dict(params.get("metadata")),
            access_context=access_context(DATASET_WRITE_PERMISSION),
        )
        return finalize(result, dataset_id=dataset_id, source=source)

    if action == "rebuild_index":
        result = service.start_rebuild_index(
            dataset_id=dataset_id,
            tenant_id=str(params.get("tenant_id") or ""),
            metadata_filter=as_dict(params.get("metadata_filter")),
            background=as_bool(params.get("background"), default=True),
            max_attempts=as_int(params.get("max_attempts"), 1),
            access_context=access_context(DATASET_WRITE_PERMISSION),
        )
        return finalize(result, dataset_id=dataset_id)

    if action == "cancel_rebuild":
        job_id = str(params.get("job_id") or "").strip()
        if not job_id:
            return {"success": False, "message": "dataset_rag.cancel_rebuild 缺少 job_id 参数"}
        result = service.cancel_rebuild_job(
            dataset_id,
            job_id,
            access_context=access_context(DATASET_WRITE_PERMISSION),
        )
        return finalize(result, dataset_id=dataset_id, job_id=job_id)

    if action == "delete_document":
        document_id = str(params.get("document_id") or "").strip()
        if not document_id:
            return {
                "success": False,
                "message": "dataset_rag.delete_document 缺少 document_id 参数",
            }
        result = service.delete_document(
            dataset_id,
            document_id,
            access_context=access_context(DATASET_WRITE_PERMISSION),
        )
        return finalize(result, dataset_id=dataset_id, document_id=document_id)

    return {"success": False, "message": f"未注册的 dataset_rag 动作: {action}"}


def _registered_router_memory_v2(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    from app.services.user_memory_service import get_user_memory_service

    service = get_user_memory_service()
    user_id = str(
        params.get("user_id") or params.get("userId") or runtime_context.get("user_id") or "default"
    ).strip()
    if not user_id:
        return {"success": False, "message": f"memory_v2.{action} 缺少 user_id 参数"}

    def as_float(value: Any, default: float) -> tuple[float, str]:
        if value in (None, ""):
            return default, ""
        try:
            return float(value), ""
        except (TypeError, ValueError):
            return default, "confidence 必须是数字"

    if action == "propose_candidate":
        memory_type = str(params.get("memory_type") or params.get("type") or "preference").strip()
        key = str(params.get("key") or "").strip()
        if not key:
            return {"success": False, "message": "memory_v2.propose_candidate 缺少 key 参数"}
        if "value" not in params:
            return {"success": False, "message": "memory_v2.propose_candidate 缺少 value 参数"}
        confidence, error = as_float(params.get("confidence"), 0.5)
        if error:
            return {"success": False, "message": error}
        try:
            return service.propose_memory_candidate(
                user_id,
                memory_type,
                key,
                params.get("value"),
                source=str(params.get("source") or "memory_v2_api"),
                confidence=confidence,
                evidence=params.get("evidence")
                if isinstance(params.get("evidence"), list)
                else None,
            )
        except ValueError as exc:
            return {"success": False, "message": str(exc)}

    memory_id = str(params.get("memory_id") or params.get("id") or "").strip()
    if not memory_id:
        return {"success": False, "message": f"memory_v2.{action} 缺少 memory_id 参数"}

    if action == "confirm":
        correction = (
            params.get("correction") if isinstance(params.get("correction"), dict) else None
        )
        return service.confirm_memory_candidate(user_id, memory_id, correction=correction)

    if action == "reject":
        return service.reject_memory_candidate(
            user_id,
            memory_id,
            reason=str(params.get("reason") or ""),
        )

    if action == "correct":
        return service.correct_memory(
            user_id,
            memory_id,
            value=params.get("value") if "value" in params else None,
            key=str(params.get("key")) if "key" in params else None,
            reason=str(params.get("reason") or ""),
        )

    if action == "delete":
        return service.delete_memory(
            user_id,
            memory_id,
            reason=str(params.get("reason") or ""),
        )

    return {"success": False, "message": f"未注册的 memory_v2 动作: {action}"}


def _registered_router_excel_analysis(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    file_path = str(params.get("file_path") or "").strip()
    if not file_path:
        excel_ctx = (
            runtime_context.get("excel_analysis")
            if isinstance(runtime_context.get("excel_analysis"), dict)
            else None
        )
        if not excel_ctx:
            last_ctx = runtime_context.get("last_excel_analysis_context")
            if isinstance(last_ctx, dict):
                excel_ctx = (
                    last_ctx.get("result") if isinstance(last_ctx.get("result"), dict) else last_ctx
                )
        if isinstance(excel_ctx, dict):
            file_path = str(excel_ctx.get("file_path") or "").strip()
    if not file_path:
        return {"success": False, "message": "excel_analysis 缺少 file_path 参数"}

    question = str(params.get("question") or "").strip()

    try:
        from app.infrastructure.skills.excel_analyzer.excel_template_analyzer import (
            get_excel_analyzer_skill,
        )
        from app.infrastructure.skills.excel_toolkit.excel_toolkit import get_excel_toolkit_skill
    except ImportError:
        return {"success": False, "message": "Excel Skill 未正确安装"}

    toolkit_skill = get_excel_toolkit_skill()
    analyzer_skill = get_excel_analyzer_skill()

    if action == "read":
        result = toolkit_skill.execute(file_path=file_path, action="view")
        return result

    if action == "structure":
        result = analyzer_skill.execute(file_path=file_path)
        return result

    if action == "statistics":
        view_result = toolkit_skill.execute(file_path=file_path, action="view")
        if not view_result.get("success"):
            return view_result
        content = view_result.get("content") or []
        total_rows = view_result.get("row_count") or 0
        all_values = []
        for row in content:
            for cell in row.get("cells") or []:
                v = cell.get("value")
                if v is not None:
                    try:
                        all_values.append(float(v))
                    except (TypeError, ValueError):
                        pass
        if all_values:
            stats = {
                "count": len(all_values),
                "sum": round(sum(all_values), 4),
                "avg": round(sum(all_values) / len(all_values), 4),
                "min": min(all_values),
                "max": max(all_values),
            }
        else:
            stats = {"count": 0}
        return {
            "success": True,
            "file_path": file_path,
            "total_rows": total_rows,
            "statistics": stats,
        }

    if action == "query":
        view_result = toolkit_skill.execute(file_path=file_path, action="view")
        if not view_result.get("success"):
            return view_result
        content = view_result.get("content") or []
        if not question:
            return {"success": True, "data": content[:20]}
        question_lower = question.lower()
        if any(kw in question_lower for kw in ["多少", "总和", "总计", "total", "sum"]):
            all_vals = []
            for row in content:
                for cell in row.get("cells") or []:
                    try:
                        all_vals.append(float(cell.get("value")))
                    except (TypeError, ValueError):
                        pass
            total = sum(all_vals) if all_vals else 0
            return {"success": True, "answer": f"所有数值总和为 {round(total, 4)}", "total": total}
        if any(kw in question_lower for kw in ["最大", "最高", "max"]):
            all_vals = [
                float(c.get("value"))
                for row in content
                for c in (row.get("cells") or [])
                if c.get("value") is not None
            ]
            try:
                mx = max(all_vals)
                return {"success": True, "answer": f"最大值为 {mx}", "max": mx}
            except ValueError:
                return {"success": True, "answer": "未找到数值"}
        return {
            "success": True,
            "data": content[:20],
            "message": f"已读取前 {min(20, len(content))} 行数据",
        }

    return {"success": False, "message": f"未知 excel_analysis action: {action}"}


def _registered_router_generate_office_document(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if action != "execute":
        return {"success": False, "message": f"未知 generate_office_document action: {action}"}

    payload = dict(params or {})
    payload.setdefault("user_request", user_message)
    try:
        import json

        from app.application.tools.workflow import execute_workflow_tool

        raw = execute_workflow_tool(
            "generate_office_document",
            payload,
            workspace_root=runtime_context.get("workspace_root"),
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return parsed if isinstance(parsed, dict) else {"success": False, "message": str(raw)}
    except RECOVERABLE_ERRORS as err:
        logger.error("generate_office_document 执行失败: %s", err, exc_info=True)
        return {"success": False, "message": f"文档生成失败：{str(err)}"}


def _registered_router_excel_vector_index(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if action == "execute":
        file_path = str(params.get("file_path") or "").strip()
        if not file_path:
            return {"success": False, "message": "缺少 file_path"}
        index_name = str(params.get("index_name") or "").strip() or None
        index_id = str(params.get("index_id") or "").strip() or None
        try:
            from app.fastapi_routes.excel_vector import get_excel_vector_ingest_app_service

            result = get_excel_vector_ingest_app_service().ingest_excel(
                file_path=file_path,
                index_name=index_name,
                index_id=index_id,
            )
        except RECOVERABLE_ERRORS as err:
            logger.error("excel_vector_index 执行失败: %s", err, exc_info=True)
            return {"success": False, "message": str(err), "error_code": "excel_vector_exception"}
        payload = dict(result or {})
        if payload.get("success") and payload.get("index_id"):
            payload["excel_vector_index_id"] = payload.get("index_id")
            payload["excel_index_id"] = payload.get("index_id")
        return payload

    if action == "query":
        index_id = str(params.get("index_id") or "").strip()
        query_text = str(params.get("query") or params.get("query_text") or "").strip()
        if not index_id:
            return {"success": False, "message": "缺少 index_id"}
        if not query_text:
            return {"success": False, "message": "缺少 query"}
        try:
            top_k = int(params.get("top_k", 5))
        except (TypeError, ValueError):
            top_k = 5
        try:
            from app.fastapi_routes.excel_vector import get_excel_vector_search_app_service

            return dict(
                get_excel_vector_search_app_service().query(
                    index_id=index_id,
                    query_text=query_text,
                    top_k=top_k,
                )
                or {}
            )
        except RECOVERABLE_ERRORS as err:
            logger.error("excel_vector_index query 失败: %s", err, exc_info=True)
            return {"success": False, "message": str(err), "error_code": "excel_vector_exception"}

    return {"success": False, "message": f"未知 excel_vector_index action: {action}"}


def _ocr_artifact_payload(
    *,
    text: str,
    file_path: str = "",
    structured_data: dict[str, Any] | None = None,
    analysis: dict[str, Any] | None = None,
    confidence: Any = 0,
) -> dict[str, Any]:
    return {
        "artifact_type": "ocr_text",
        "name": "ocr_result",
        "source": "ocr.recognize",
        "uri": file_path,
        "mime_type": "image/*",
        "summary": "OCR 解析结果",
        "fields": [
            {"name": key, "value": value}
            for key, value in dict(structured_data or {}).items()
            if value not in (None, "", [], {})
        ][:20],
        "preview": {
            "text": text[:1000],
            "confidence": confidence,
            "structured_data": dict(structured_data or {}),
            "analysis": dict(analysis or {}),
        },
        "metadata": {
            "parser_used": "ocr",
            "text": text,
            "success": True,
        },
    }


def _registered_router_ocr(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    try:
        from app.fastapi_routes.ocr import _get_ocr_service

        if action == "request":
            request_id = str(params.get("request_id") or "").strip()
            image_url = str(params.get("image_url") or "").strip()
            if not request_id:
                return {"success": False, "message": "缺少 request_id"}
            if not image_url:
                return {"success": False, "message": "缺少 image_url"}
            ocr_type = str(params.get("ocr_type") or "general").strip() or "general"
            user_id = str(
                params.get("user_id") or runtime_context.get("user_id") or "system"
            ).strip()
            from app.neuro_bus.domains.ocr_domain import get_ocr_domain

            ok = get_ocr_domain().emit_ocr_requested(
                request_id=request_id,
                image_url=image_url,
                ocr_type=ocr_type,
                user_id=user_id or "system",
            )
            return {
                "success": bool(ok),
                "message": "OCR 请求已发布" if ok else "OCR 请求发布失败",
                "request_id": request_id,
                "image_url": image_url,
                "ocr_type": ocr_type,
                "user_id": user_id or "system",
                "event": "ocr.requested",
                "published": bool(ok),
            }
        service = _get_ocr_service()
        if action == "recognize":
            file_path = str(params.get("file_path") or "").strip()
            if not file_path:
                return {"success": False, "message": "缺少 file_path"}
            result = dict(service.recognize_file(file_path) or {})
            if result.get("success"):
                text = str(result.get("text") or "")
                result.setdefault("artifacts", [])
                result["artifacts"] = list(result["artifacts"]) + [
                    _ocr_artifact_payload(
                        text=text,
                        file_path=str(result.get("file_path") or file_path),
                        confidence=result.get("confidence", result.get("ocr_confidence", 0)),
                    )
                ]
            return result

        if action == "extract":
            text = str(params.get("text") or "").strip()
            if not text:
                return {"success": False, "message": "缺少 text"}
            data = dict(service.extract_structured_data(text) or {})
            return {"success": True, "message": "提取成功", "data": data}

        if action == "analyze":
            text = str(params.get("text") or "").strip()
            if not text:
                return {"success": False, "message": "缺少 text"}
            data = dict(service.analyze_text(text) or {})
            return {"success": True, "message": "分析成功", "data": data}

        if action == "recognize_and_extract":
            file_path = str(params.get("file_path") or "").strip()
            if not file_path:
                return {"success": False, "message": "缺少 file_path"}
            recognize_result = dict(service.recognize_file(file_path) or {})
            if not recognize_result.get("success"):
                return recognize_result
            text = str(recognize_result.get("text") or "")
            structured_data = dict(service.extract_structured_data(text) or {})
            analysis = dict(service.analyze_text(text) or {})
            return {
                "success": True,
                "message": "识别和提取成功",
                "text": text,
                "data": structured_data,
                "analysis": analysis,
                "artifacts": [
                    _ocr_artifact_payload(
                        text=text,
                        file_path=str(recognize_result.get("file_path") or file_path),
                        structured_data=structured_data,
                        analysis=analysis,
                        confidence=analysis.get("confidence", 0),
                    )
                ],
            }
    except RECOVERABLE_ERRORS as err:
        logger.error("ocr 工具执行失败: %s", err, exc_info=True)
        return {"success": False, "message": str(err), "error_code": "ocr_exception"}

    return {"success": False, "message": f"未知 ocr action: {action}"}


def _execute_excel_import_records(records: list[dict[str, Any]]) -> dict:
    if not records:
        return {"success": False, "message": "没有可导入的记录"}

    try:
        from app.bootstrap import get_products_service

        products_service = get_products_service()
        customer_service = None
        customer_service_error = ""
        try:
            from app.bootstrap import get_customer_app_service

            customer_service = get_customer_app_service()
        except RECOVERABLE_ERRORS as customer_err:
            customer_service_error = str(customer_err)
            logger.warning("客户服务不可用，降级为仅产品入库: %s", customer_err)

        created_units = 0
        created_products = 0
        skipped_products = 0
        touched_units: set[str] = set()

        for row in records:
            unit_name = str(row.get("unit_name") or "").strip()
            product_name = str(row.get("product_name") or "").strip()
            model_number = str(row.get("model_number") or "").strip().upper()
            unit_price = float(row.get("unit_price") or 0.0)
            touched_units.add(unit_name)

            if customer_service is not None:
                matched = customer_service.match_purchase_unit(unit_name)
                if not matched:
                    create_unit = customer_service.create({"customer_name": unit_name})
                    if create_unit.get("success"):
                        created_units += 1

            exists_result = products_service.get_products(
                unit_name=unit_name,
                model_number=model_number or None,
                keyword=(product_name or model_number or None),
                page=1,
                per_page=5,
            )
            existed = False
            if exists_result.get("success"):
                rows_data = exists_result.get("data") or []
                for item in rows_data:
                    item_name = str(item.get("name") or item.get("product_name") or "").strip()
                    item_model = str(item.get("model_number") or "").strip().upper()
                    if model_number and item_model == model_number:
                        existed = True
                        break
                    if product_name and item_name == product_name:
                        existed = True
                        break
            if existed:
                skipped_products += 1
                continue

            create_product = products_service.create_product(
                {
                    "name": product_name or model_number,
                    "product_name": product_name or model_number,
                    "product_code": model_number or None,
                    "model_number": model_number or None,
                    "unit_price": unit_price,
                    "price": unit_price,
                    "unit": unit_name,
                }
            )
            if create_product.get("success"):
                created_products += 1

        return {
            "success": True,
            "message": "Excel 导入完成",
            "imported_count": len(records),
            "data": {
                "result": {
                    "records": len(records),
                    "touched_units": len(touched_units),
                    "created_units": created_units,
                    "created_products": created_products,
                    "skipped_products": skipped_products,
                    "unit_service_available": customer_service is not None,
                    "unit_service_error": customer_service_error,
                }
            },
        }
    except RECOVERABLE_ERRORS as err:
        logger.error("Excel 导入执行失败: %s", err, exc_info=True)
        return {"success": False, "message": f"导入执行失败：{str(err)}"}


def _registered_router_excel_import(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if action == "execute_import":
        pending_import_id = str(params.get("pending_import_id") or "").strip()
        if not pending_import_id:
            return {"success": False, "message": "缺少 pending_import_id 参数"}

        from app.application import get_ai_chat_app_service

        ai_chat_service = get_ai_chat_app_service()
        pending_imports = getattr(ai_chat_service, "_pending_excel_imports", {})
        import_data = pending_imports.get(pending_import_id)

        if not import_data:
            return {"success": False, "message": "未找到待处理的导入数据或已过期"}

        records = import_data.get("records", [])
        if not isinstance(records, list):
            return {"success": False, "message": "待导入记录格式错误"}
        result = _execute_excel_import_records([r for r in records if isinstance(r, dict)])
        if result.get("success"):
            pending_imports.pop(pending_import_id, None)
        return result

    if action == "import_records":
        records = params.get("records")
        if not isinstance(records, list):
            return {"success": False, "message": "records 必须是数组"}
        return _execute_excel_import_records([r for r in records if isinstance(r, dict)])

    return {"success": False, "message": f"未知 excel_import action: {action}"}


def _registered_router_unit_products_import(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if action != "execute_import":
        return {"success": False, "message": f"未知 unit_products_import action: {action}"}

    saved_name = str(params.get("saved_name") or "").strip()
    unit_name = str(params.get("unit_name") or "").strip()
    if not saved_name:
        return {"success": False, "message": "缺少 saved_name 参数"}
    if not unit_name:
        return {"success": False, "message": "缺少 unit_name 参数"}

    try:
        from app.application import get_unit_products_import_app_service

        service = get_unit_products_import_app_service()
        result = service.import_unit_products(
            saved_name=saved_name,
            unit_name=unit_name,
            create_purchase_unit=bool(params.get("create_purchase_unit", True)),
            skip_duplicates=bool(params.get("skip_duplicates", True)),
        )
        if result.get("success"):
            created_unit = bool(result.get("created_unit", False))
            imported_count = int(result.get("created_products") or result.get("imported") or 0)
            result.setdefault("created_customers", 1 if created_unit else 0)
            result.setdefault("created_products", imported_count)
            data = result.get("data")
            if not isinstance(data, dict):
                data = {}
            data.setdefault("unit_name", unit_name)
            data.setdefault("saved_name", saved_name)
            data.setdefault("created_unit", created_unit)
            data.setdefault("imported", int(result.get("imported") or imported_count))
            data.setdefault("skipped_duplicates", int(result.get("skipped_duplicates") or 0))
            result["data"] = data
        return result
    except RECOVERABLE_ERRORS as err:
        logger.error("unit products 导入执行失败: %s", err, exc_info=True)
        return {"success": False, "message": f"导入执行失败：{str(err)}"}


class _WorkflowRouterMap(dict):
    _hidden_keys = {"employee", "business_db"}

    def keys(self):
        return [key for key in super().keys() if key not in self._hidden_keys]


_REGISTERED_WORKFLOW_ROUTERS: dict[str, Callable[..., dict]] = _WorkflowRouterMap(
    {
        "normal_slot_dispatch": _registered_router_normal_slot_dispatch,
        "customers": _registered_router_customers,
        "products": _registered_router_products,
        "materials": _registered_router_materials,
        "inventory": _registered_router_inventory,
        "purchase": _registered_router_purchase,
        "finance": _registered_router_finance,
        "shipment_records": _registered_router_shipment_records,
        "shipment_orders": _registered_router_shipment_orders,
        "business_event": _registered_router_business_event,
        "system_maintenance": _registered_router_system_maintenance,
        "business_docking": _registered_router_business_docking_family,
        "template_extract": _registered_router_business_docking_family,
        "excel_analyzer": _registered_router_excel_analyzer,
        "excel_toolkit": _registered_router_excel_toolkit,
        "label_template_generator": _registered_router_label_template_generator,
        "document_template": _registered_router_document_template,
        "template_preview": _registered_router_template_preview,
        "wechat": _registered_router_wechat,
        "print": _registered_router_print,
        "printer_list": _registered_router_printer_list,
        "settings": _registered_router_settings,
        "employee": _registered_router_employee,
        "business_db": _registered_router_business_db,
        "dataset_rag": _registered_router_dataset_rag,
        "memory_v2": _registered_router_memory_v2,
        "excel_analysis": _registered_router_excel_analysis,
        "generate_office_document": _registered_router_generate_office_document,
        "excel_vector_index": _registered_router_excel_vector_index,
        "ocr": _registered_router_ocr,
        "excel_import": _registered_router_excel_import,
        "unit_products_import": _registered_router_unit_products_import,
    }
)


def execute_registered_workflow_tool(tool_id: str, action: str, params: dict | None = None) -> dict:
    """统一 dispatcher（供 WorkflowEngine 与 /api/tools/execute 复用）。"""
    from app.application.normal_chat_dispatch import resolve_tool_execution_profile

    params = dict(params or {})
    runtime_context = dict(params.pop("_runtime_context", None) or {})
    profile = resolve_tool_execution_profile(runtime_context)
    user_message = str(runtime_context.get("message") or "").strip()

    router = _REGISTERED_WORKFLOW_ROUTERS.get(tool_id)
    if router is not None:
        return router(action, params, runtime_context, profile, user_message)
    try:
        from app.mod_sdk.employee_tool_registry import execute_employee_tool, is_employee_tool

        if is_employee_tool(tool_id):
            workspace_root = runtime_context.get("workspace_root")
            raw = execute_employee_tool(
                tool_id,
                {**params, "task": params.get("task") or user_message},
                str(workspace_root) if workspace_root else None,
            )
            import json

            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"success": False, "message": raw}
    except RECOVERABLE_ERRORS:
        logger.debug("employee tool direct dispatch skipped tool=%s", tool_id, exc_info=True)
    return {"success": False, "message": f"未注册的工具动作: {tool_id}.{action}"}
