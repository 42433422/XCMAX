# mypy: disable-error-code="no-any-return"
"""ERP 域工作流路由：客户/产品/物料/库存/采购/销售/报表/资金。"""

from __future__ import annotations

import logging
from typing import Any, cast

logger = logging.getLogger(__name__)
from app.services.tools_workflow_common import (
    _business_db_target_candidates,
)

# Module-load-time default so a globals patch cannot skew facade-override detection.
_DEFAULT_TARGET_CANDIDATES = _business_db_target_candidates


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


def _resolve_target_candidates():
    """目标解析晚绑定：facade 属性 patch 与本模块全局 patch 两个接缝等价生效。"""
    from app.services import tools_workflow_registered as facade

    resolved = getattr(facade, "_business_db_target_candidates", None)
    if resolved is not None and resolved is not _DEFAULT_TARGET_CANDIDATES:
        return resolved
    return _business_db_target_candidates


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
    if action in {"create", "ensure_exists", "upsert"}:
        from app.services.business_db_customer_mutations import execute_customer_create_like

        return execute_customer_create_like(
            action, params, svc=svc, resolve_targets=_resolve_target_candidates()
        )
    if action == "query":
        keyword = str(params.get("keyword") or unit_name or "").strip()
        result = svc.get_all(keyword=keyword, page=1, per_page=20)
        return {
            "success": bool(result.get("success")),
            "data": result.get("data", []),
            "raw": result,
        }
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
    if action == "add_address":
        payload = dict(params or {})
        return dict(svc.add_address(payload) or {})
    if action == "set_credit_limit":
        customer_id = int(params.get("customer_id") or params.get("id") or 0)
        if customer_id <= 0:
            return {"success": False, "message": "缺少 customer_id"}
        return dict(
            svc.set_credit_limit(
                customer_id, params.get("credit_limit") or params.get("limit") or 0
            )
            or {}
        )
    if action == "get_addresses":
        customer_id = int(params.get("customer_id") or params.get("id") or 0)
        if customer_id <= 0:
            return {"success": False, "message": "缺少 customer_id"}
        return dict(svc.get_addresses(customer_id) or {})
    return {"success": False, "message": f"未注册的 customers 动作: {action}"}


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
        return float(str(value))

    if action == "create_storage_location":
        return cast("dict[Any, Any]", svc.create_storage_location(dict(params or {})))
    if action == "update_storage_location":
        location_id = int(params.get("location_id") or 0)
        payload = {k: v for k, v in params.items() if k != "location_id"}
        return cast("dict[Any, Any]", svc.update_storage_location(location_id, payload))
    if action == "create_warehouse":
        return cast("dict[Any, Any]", svc.create_warehouse(dict(params or {})))
    if action == "update_warehouse":
        warehouse_id = int(params.get("warehouse_id") or 0)
        payload = {k: v for k, v in params.items() if k != "warehouse_id"}
        return cast("dict[Any, Any]", svc.update_warehouse(warehouse_id, payload))
    if action == "delete_warehouse":
        return cast("dict[Any, Any]", svc.delete_warehouse(int(params.get("warehouse_id") or 0)))
    if action == "stock_in":
        return cast(
            "dict[Any, Any]",
            svc.inventory_in(
                product_id=params.get("product_id"),
                warehouse_id=params.get("warehouse_id"),
                quantity=params.get("quantity"),
                **({"model_number": params["model_number"]} if "model_number" in params else {}),
                **(
                    {"warehouse_name": params["warehouse_name"]}
                    if "warehouse_name" in params
                    else {}
                ),
                batch_no=params.get("batch_no"),
                location_id=params.get("location_id"),
                unit_price=_float_or_none(params.get("unit_price")),
                reference_type=params.get("reference_type"),
                reference_id=params.get("reference_id"),
                operator=params.get("operator"),
                remark=params.get("remark"),
            ),
        )
    if action == "stock_out":
        return cast(
            "dict[Any, Any]",
            svc.inventory_out(
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
            ),
        )
    if action == "transfer":
        return cast(
            "dict[Any, Any]",
            svc.inventory_transfer(
                product_id=params.get("product_id"),
                from_warehouse_id=params.get("from_warehouse_id"),
                to_warehouse_id=params.get("to_warehouse_id"),
                quantity=float(params.get("quantity", 0)),
                batch_no=params.get("batch_no"),
                from_location_id=params.get("from_location_id"),
                to_location_id=params.get("to_location_id"),
                operator=params.get("operator"),
                remark=params.get("remark"),
            ),
        )
    if action == "low_stock_alert":
        from app.application.material_app_service import get_material_app_service

        threshold = params.get("threshold")
        return get_material_app_service().get_low_stock_materials(
            float(threshold) if threshold is not None else None
        )
    if action == "replenishment_suggest":
        from app.services.replenishment_service import suggest_replenishment

        return suggest_replenishment(
            threshold=params.get("threshold"), per_page=int(params.get("per_page") or 50)
        )
    if action == "inventory_count":
        from app.services.inventory_service import InventoryService

        inv_svc = InventoryService()
        return inv_svc.inventory_count(
            product_id=int(params.get("product_id") or 0),
            warehouse_id=int(params.get("warehouse_id") or 0),
            actual_quantity=float(params.get("actual_quantity", 0)),
            batch_no=params.get("batch_no"),
            location_id=params.get("location_id"),
            operator=params.get("operator"),
            remark=params.get("remark"),
            confirmed=bool(params.get("confirmed", False)),
        )
    if action == "query_transactions":
        from app.services.inventory_service import InventoryService

        inv_svc = InventoryService()
        return inv_svc.query_transactions(
            product_id=params.get("product_id"),
            warehouse_id=params.get("warehouse_id"),
            start_date=params.get("start_date"),
            end_date=params.get("end_date"),
            page=int(params.get("page") or 1),
            per_page=int(params.get("per_page") or 20),
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
    if action in ("list_suppliers", "get_suppliers", "query_suppliers"):
        return cast(
            "dict[Any, Any]",
            svc.get_suppliers(
                status=params.get("status"),
                keyword=str(params.get("keyword") or params.get("search") or "").strip() or None,
            ),
        )
    if action in ("list_orders", "get_orders", "list_purchase_orders", "query_orders"):
        return cast(
            "dict[Any, Any]",
            svc.get_purchase_orders(
                supplier_id=params.get("supplier_id"),
                status=params.get("status"),
                page=int(params.get("page") or 1),
                per_page=int(params.get("per_page") or 20),
            ),
        )
    if action in ("list_inbounds", "get_inbounds", "list_purchase_inbounds", "query_inbounds"):
        return cast(
            "dict[Any, Any]",
            svc.get_purchase_inbounds(
                supplier_id=params.get("supplier_id"),
                order_id=params.get("order_id"),
                page=int(params.get("page") or 1),
                per_page=int(params.get("per_page") or 20),
            ),
        )
    if action == "create_supplier":
        return cast("dict[Any, Any]", svc.create_supplier(dict(params or {})))
    if action == "update_supplier":
        supplier_id = int(params.get("supplier_id") or 0)
        payload = {k: v for k, v in params.items() if k != "supplier_id"}
        return cast("dict[Any, Any]", svc.update_supplier(supplier_id, payload))
    if action == "delete_supplier":
        return cast("dict[Any, Any]", svc.delete_supplier(int(params.get("supplier_id") or 0)))
    if action == "create_order":
        return cast("dict[Any, Any]", svc.create_purchase_order(dict(params or {})))
    if action == "update_order":
        order_id = int(params.get("order_id") or 0)
        payload = {k: v for k, v in params.items() if k != "order_id"}
        return cast("dict[Any, Any]", svc.update_purchase_order(order_id, payload))
    if action == "approve_order":
        return cast(
            "dict[Any, Any]",
            svc.approve_purchase_order(
                int(params.get("order_id") or 0), str(params.get("approver") or "system")
            ),
        )
    if action == "cancel_order":
        return cast("dict[Any, Any]", svc.cancel_purchase_order(int(params.get("order_id") or 0)))
    if action == "create_inbound":
        return cast("dict[Any, Any]", svc.create_purchase_inbound(dict(params or {})))
    return {"success": False, "message": f"未注册的 purchase 动作: {action}"}


def _registered_router_sales(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    from app.application.sales_app_service import SalesAppService

    svc = SalesAppService()
    if action == "create_order":
        from app.application.sales_order_creation import create_confirmed_order

        return create_confirmed_order(dict(params or {}))
    if action in ("query", "list", "get_orders"):
        return svc.query(
            status=params.get("status"),
            customer_id=params.get("customer_id"),
            customer_name=params.get("customer_name"),
            keyword=str(params.get("keyword") or params.get("search") or "").strip() or None,
            page=int(params.get("page") or 1),
            per_page=int(params.get("per_page") or 20),
        )
    if action == "quote":
        return svc.quote(dict(params or {}))
    if action == "confirm":
        return svc.confirm(int(params.get("order_id") or 0))
    if action == "deliver":
        return svc.deliver(
            int(params.get("order_id") or 0),
            int(params.get("item_id") or 0),
            float(params.get("quantity") or 0.0),
            warehouse_id=int(params.get("warehouse_id") or 0),
            idempotency_key=params.get("idempotency_key"),
        )
    if action == "invoice":
        return svc.invoice(int(params.get("order_id") or 0))
    if action == "credit_note":
        return svc.credit_note(int(params.get("order_id") or 0))
    if action == "payment":
        amount = params.get("amount")
        return svc.payment(
            int(params.get("order_id") or 0), float(amount) if amount is not None else None
        )
    if action == "refund":
        return svc.refund(int(params.get("allocation_id") or 0))
    if action == "cancel":
        return svc.cancel(int(params.get("order_id") or 0))
    if action == "execute_closed_loop":
        return svc.execute_closed_loop(dict(params["payload"]))
    return {"success": False, "message": f"未注册的 sales 动作: {action}"}


def _registered_router_reports(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    from app.services.report_service import ReportService

    svc = ReportService()
    if action == "sales_summary":
        return svc.get_sales_report(
            start_date=params.get("start_date"),
            end_date=params.get("end_date"),
            group_by=str(params.get("group_by") or "product"),
            customer_id=params.get("customer_id"),
        )
    if action == "inventory_summary":
        return svc.get_inventory_report(
            warehouse_id=params.get("warehouse_id"),
            category=params.get("category"),
            model_number=params.get("model_number"),
        )
    if action == "purchase_summary":
        return svc.get_purchase_report(
            start_date=params.get("start_date"),
            end_date=params.get("end_date"),
            group_by=str(params.get("group_by") or "supplier"),
        )
    if action == "dashboard":
        return svc.get_dashboard_summary()
    if action == "export":
        report_type = str(params.get("report_type") or "report")
        rows = params.get("data")
        if rows is None and report_type == "sales":
            report = svc.get_sales_report(
                start_date=params.get("start_date"),
                end_date=params.get("end_date"),
                group_by=str(params.get("group_by") or "product"),
            )
            if not report.get("success"):
                return report
            rows = report.get("data") or []
        exported = svc.export_to_excel(
            report_type=report_type,
            data=rows or [],
            filename=str(params.get("filename") or "report"),
        )
        run_id = str(runtime_context.get("run_id") or "")
        if run_id and exported.get("success"):
            from app.application.agent_orchestrator.artifact_files import store_spreadsheet

            artifact = store_spreadsheet(run_id, exported["data"], name=exported["filename"])
            return {
                "success": True,
                "message": "报表文件已生成",
                "row_count": len(rows or []),
                "artifacts": [artifact],
            }
        return exported
    return {"success": False, "message": f"未注册的 reports 动作: {action}"}


def _registered_router_finance(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if str(runtime_context.get("service_source") or "") == "fastapi_finance_route":
        from app.fastapi_routes import finance as finance_route

        svc = finance_route._svc()
    else:
        from app.application.finance_app_service import FinanceAppService

        svc = FinanceAppService()
    if action in ("list_transactions", "list", "query", "get_transactions"):
        return cast(
            "dict[Any, Any]",
            svc.list_transactions(
                transaction_type=params.get("transaction_type"),
                status=params.get("status"),
                page=int(params.get("page") or 1),
                per_page=int(params.get("per_page") or 20),
            ),
        )
    if action == "create_transaction":
        return cast("dict[Any, Any]", svc.create_transaction(dict(params or {})))
    if action == "update_transaction":
        transaction_id = int(params.get("transaction_id") or 0)
        payload = {k: v for k, v in params.items() if k != "transaction_id"}
        return cast("dict[Any, Any]", svc.update_transaction(transaction_id, payload))
    if action == "delete_transaction":
        return cast(
            "dict[Any, Any]", svc.delete_transaction(int(params.get("transaction_id") or 0))
        )
    if action in ("ledger_query", "query_ledger"):
        from app.services.accounting_services import query_financial_ledger

        return query_financial_ledger(**dict(params or {}))
    if action == "journal_entry_create":
        from app.services.accounting_services import create_journal_entry

        return create_journal_entry(dict(params or {}))
    if action == "journal_entry_reverse":
        from app.services.accounting_services import journal_entry_reverse

        entry_id = int(params.get("entry_id") or params.get("id") or 0)
        if entry_id <= 0:
            return {"success": False, "message": "缺少 entry_id"}
        return journal_entry_reverse(entry_id, description=params.get("description"))
    if action == "aging_report":
        from app.services.accounting_services import aging_report

        raw_type = str(params.get("account_type") or params.get("party_type") or "应收").strip()
        if raw_type in ("应收", "receivable", "客户"):
            party_type = "receivable"
        elif raw_type in ("应付", "payable", "供应商"):
            party_type = "payable"
        else:
            party_type = raw_type
        party_id = int(params.get("party_id") or params.get("customer_id") or 0)
        return aging_report(party_type=party_type, party_id=party_id)
    if action == "chart_seed":
        from app.services.accounting_services import seed_default_chart_of_accounts

        return seed_default_chart_of_accounts()
    return {"success": False, "message": f"未注册的 finance 动作: {action}"}
