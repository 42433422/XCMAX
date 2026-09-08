# mypy: disable-error-code="no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.services.tools_workflow_registered")


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
        return _facade().cast("dict[Any, Any]", svc.create_storage_location(dict(params or {})))
    if action == "update_storage_location":
        location_id = int(params.get("location_id") or 0)
        payload = {k: v for k, v in params.items() if k != "location_id"}
        return _facade().cast("dict[Any, Any]", svc.update_storage_location(location_id, payload))
    if action == "create_warehouse":
        return _facade().cast("dict[Any, Any]", svc.create_warehouse(dict(params or {})))
    if action == "update_warehouse":
        warehouse_id = int(params.get("warehouse_id") or 0)
        payload = {k: v for k, v in params.items() if k != "warehouse_id"}
        return _facade().cast("dict[Any, Any]", svc.update_warehouse(warehouse_id, payload))
    if action == "delete_warehouse":
        return _facade().cast(
            "dict[Any, Any]", svc.delete_warehouse(int(params.get("warehouse_id") or 0))
        )
    if action in {"stock_in", "stock_out", "transfer"}:
        import math

        raw_quantity = params.get("quantity")
        if raw_quantity is None:
            return {"success": False, "message": "库存操作数量必须为有限正数"}
        try:
            quantity = float(raw_quantity)
        except (TypeError, ValueError, OverflowError):
            return {"success": False, "message": "库存操作数量必须为有限正数"}
        if isinstance(raw_quantity, bool) or not math.isfinite(quantity) or quantity <= 0:
            return {"success": False, "message": "库存操作数量必须为有限正数"}
    if action == "stock_in":
        return _facade().cast(
            "dict[Any, Any]",
            svc.inventory_in(
                product_id=params.get("product_id"),
                warehouse_id=params.get("warehouse_id"),
                quantity=quantity,
                batch_no=params.get("batch_no"),
                location_id=params.get("location_id"),
                unit_price=_float_or_none(params.get("unit_price")),
                reference_type=params.get("reference_type"),
                reference_id=params.get("reference_id"),
                operator=params.get("operator"),
                remark=params.get("remark"),
                **(
                    {"requested_unit": str(params["requested_unit"])}
                    if "requested_unit" in params
                    else {}
                ),
            ),
        )
    if action == "stock_out":
        return _facade().cast(
            "dict[Any, Any]",
            svc.inventory_out(
                product_id=params.get("product_id"),
                warehouse_id=params.get("warehouse_id"),
                quantity=quantity,
                unit_price=_float_or_none(params.get("unit_price")),
                batch_no=params.get("batch_no"),
                location_id=params.get("location_id"),
                reference_type=params.get("reference_type"),
                reference_id=params.get("reference_id"),
                operator=params.get("operator"),
                remark=params.get("remark"),
            ),
        )
    if action == "transfer":
        return _facade().cast(
            "dict[Any, Any]",
            svc.inventory_transfer(
                product_id=params.get("product_id"),
                from_warehouse_id=params.get("from_warehouse_id"),
                to_warehouse_id=params.get("to_warehouse_id"),
                quantity=quantity,
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

        raw_quantity = params.get("actual_quantity")
        try:
            actual_quantity = (
                float(raw_quantity) if not isinstance(raw_quantity, bool) else raw_quantity
            )
        except (TypeError, ValueError, OverflowError):
            return {"success": False, "message": "盘点数量必须为有限非负数"}
        inv_svc = InventoryService()
        return inv_svc.inventory_count(
            product_id=int(params.get("product_id") or 0),
            warehouse_id=int(params.get("warehouse_id") or 0),
            actual_quantity=actual_quantity,
            batch_no=params.get("batch_no"),
            location_id=params.get("location_id"),
            operator=params.get("operator"),
            remark=params.get("remark"),
            confirmed=params.get("confirmed", False),
        )
    if action == "query_transactions":
        from datetime import datetime, time

        from app.services.inventory_service import InventoryService

        def parse_date(value, *, end=False):
            if value is None or value == "":
                return None
            if isinstance(value, datetime):
                return value
            parsed = datetime.fromisoformat(str(value))
            if end and len(str(value)) == 10:
                parsed = datetime.combine(parsed.date(), time.max)
            return parsed

        try:
            start_date = parse_date(params.get("start_date"))
            end_date = parse_date(params.get("end_date"), end=True)
            if start_date and end_date and start_date > end_date:
                raise ValueError("reversed range")
        except (TypeError, ValueError, OverflowError):
            return {
                "success": False,
                "message": "流水查询日期无效，请使用有效日期且开始时间不晚于结束时间",
            }
        inv_svc = InventoryService()
        return inv_svc.query_transactions(
            product_id=params.get("product_id"),
            warehouse_id=params.get("warehouse_id"),
            transaction_type=params.get("transaction_type"),
            start_date=start_date,
            end_date=end_date,
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
        return _facade().cast(
            "dict[Any, Any]",
            svc.get_suppliers(
                status=params.get("status"),
                keyword=str(params.get("keyword") or params.get("search") or "").strip() or None,
            ),
        )
    if action in ("list_orders", "get_orders", "list_purchase_orders", "query_orders"):
        return _facade().cast(
            "dict[Any, Any]",
            svc.get_purchase_orders(
                supplier_id=params.get("supplier_id"),
                status=params.get("status"),
                page=int(params.get("page") or 1),
                per_page=int(params.get("per_page") or 20),
            ),
        )
    if action in ("list_inbounds", "get_inbounds", "list_purchase_inbounds", "query_inbounds"):
        return _facade().cast(
            "dict[Any, Any]",
            svc.get_purchase_inbounds(
                supplier_id=params.get("supplier_id"),
                order_id=params.get("order_id"),
                page=int(params.get("page") or 1),
                per_page=int(params.get("per_page") or 20),
            ),
        )
    if action == "create_supplier":
        return _facade().cast("dict[Any, Any]", svc.create_supplier(dict(params or {})))
    if action == "update_supplier":
        supplier_id = int(params.get("supplier_id") or 0)
        payload = {k: v for k, v in params.items() if k != "supplier_id"}
        return _facade().cast("dict[Any, Any]", svc.update_supplier(supplier_id, payload))
    if action == "delete_supplier":
        return _facade().cast(
            "dict[Any, Any]", svc.delete_supplier(int(params.get("supplier_id") or 0))
        )
    if action == "create_order":
        return _facade().cast("dict[Any, Any]", svc.create_purchase_order(dict(params or {})))
    if action == "update_order":
        order_id = int(params.get("order_id") or 0)
        payload = {k: v for k, v in params.items() if k != "order_id"}
        return _facade().cast("dict[Any, Any]", svc.update_purchase_order(order_id, payload))
    if action == "approve_order":
        return _facade().cast(
            "dict[Any, Any]",
            svc.approve_purchase_order(
                int(params.get("order_id") or 0), str(params.get("approver") or "system")
            ),
        )
    if action == "cancel_order":
        return _facade().cast(
            "dict[Any, Any]", svc.cancel_purchase_order(int(params.get("order_id") or 0))
        )
    if action == "create_inbound":
        return _facade().cast("dict[Any, Any]", svc.create_purchase_inbound(dict(params or {})))
    return {"success": False, "message": f"未注册的 purchase 动作: {action}"}


def _registered_router_sales(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    from app.application.sales_app_service import SalesAppService

    svc = SalesAppService()
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
    if action in ("confirm", "confirm_from_result"):
        order_id = params.get("order_id")
        source_id = params.get("order_node_id")
        if action == "confirm_from_result" and not source_id:
            return {"success": False, "message": "缺少前序订单节点引用"}
        if source_id:
            source = (runtime_context.get("node_outputs") or {}).get(str(source_id))
            data = source.get("data") if isinstance(source, dict) else None
            resolved = data.get("id") if isinstance(data, dict) else None
            if (
                not isinstance(source, dict)
                or source.get("success") is not True
                or type(resolved) is not int
                or resolved <= 0
                or (order_id is not None and str(order_id) != str(resolved))
            ):
                return {"success": False, "message": "前序订单结果不可用或订单编号不一致"}
            order_id = resolved
        return svc.confirm(int(order_id or 0))
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
            product_keyword=params.get("product_keyword"),
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
        from app.application.workflow.report_export_receipt import export_report_receipt

        return export_report_receipt(svc, params, runtime_context)
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
        return _facade().cast(
            "dict[Any, Any]",
            svc.list_transactions(
                transaction_type=params.get("transaction_type"),
                status=params.get("status"),
                page=int(params.get("page") or 1),
                per_page=int(params.get("per_page") or 20),
            ),
        )
    if action == "create_transaction":
        return _facade().cast("dict[Any, Any]", svc.create_transaction(dict(params or {})))
    if action == "update_transaction":
        transaction_id = int(params.get("transaction_id") or 0)
        payload = {k: v for k, v in params.items() if k != "transaction_id"}
        return _facade().cast("dict[Any, Any]", svc.update_transaction(transaction_id, payload))
    if action == "delete_transaction":
        return _facade().cast(
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
