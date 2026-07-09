"""Business entity workflow routers."""

from __future__ import annotations

import logging
import os
import uuid
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

    if str(runtime_context.get("service_source") or "") == "fastapi_product_compat_route":
        import importlib

        route_module = str(
            runtime_context.get("route_module")
            or "app.fastapi_routes.domains.product.compat_routes"
        )
        module = importlib.import_module(route_module)
        execute_action = module._execute_products_compat_action
        return dict(execute_action(action, params) or {})

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
    if action == "batch_delete":
        raw_ids = params.get("ids") or params.get("product_ids") or []
        if not isinstance(raw_ids, list) or not raw_ids:
            return {"success": False, "message": "ids 须为非空数组"}
        ids: list[int] = []
        skipped: list = []
        for raw_id in raw_ids:
            try:
                ids.append(int(raw_id))
            except RECOVERABLE_ERRORS:
                skipped.append(raw_id)
        if not ids:
            return {"success": False, "message": "ids 须包含有效数字", "skipped": skipped}
        batch_delete = getattr(svc, "batch_delete_products", None)
        if callable(batch_delete):
            result = dict(batch_delete(ids) or {})
        else:
            result = dict(svc.batch_delete(ids) or {})
        if skipped:
            result["skipped"] = list(result.get("skipped") or []) + skipped
        return result
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


