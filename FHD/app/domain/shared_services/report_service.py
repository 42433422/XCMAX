"""统计销售、库存和采购。"""

from datetime import datetime
from decimal import Decimal
from typing import Any

import pandas as pd  # noqa: F401 - compatibility patch point for existing tests/extensions
from sqlalchemy import func

from app.db.models import (
    Customer,
    InventoryLedger,
    InventoryTransaction,
    Product,
    PurchaseOrder,
    SalesOrder,
    SalesOrderItem,
    ShipmentRecord,
    Supplier,
)
from app.db.models.sales import inclusive_order_bound, sales_status_predicate
from app.db.session import get_db
from app.domain.shared_services.report_export import export_report_to_excel
from app.neuro_bus.event_publisher_mixin import NeuroEventPublisherMixin


class ReportService(NeuroEventPublisherMixin):
    @staticmethod
    def _decimal_to_float(value: Any) -> Any:
        return float(value) if isinstance(value, Decimal) else value

    def get_sales_report(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        group_by: str = "product",
        customer_id: int | None = None,
        source: str = "sales_order",
        payment_state: str | None = None,
        min_amount_exclusive: Any = None,
        region: str | None = None,
        status: str | None = None,
        customer_name: str | None = None,
        order_no: str | None = None,
    ) -> dict[str, Any]:
        """按订单汇总销售，兼容指定来源的历史发货报表。"""
        if source == "shipment":
            return self._get_sales_report_from_shipments(
                start_date, end_date, group_by, customer_id
            )
        start_date = inclusive_order_bound(start_date, end=False)
        end_date = inclusive_order_bound(end_date, end=True)
        with get_db() as db:
            query = db.query(SalesOrderItem, SalesOrder).join(
                SalesOrder, SalesOrderItem.order_id == SalesOrder.id
            )

            if start_date:
                query = query.filter(SalesOrder.created_at >= start_date)
            if end_date:
                query = query.filter(SalesOrder.created_at <= end_date)
            if customer_id:
                query = query.filter(SalesOrder.customer_id == customer_id)
            if customer_name:
                query = query.filter(SalesOrder.customer_name == customer_name)
            if order_no:
                query = query.filter(SalesOrder.order_no == str(order_no))
            if status:
                query = query.filter(sales_status_predicate(status))
            if payment_state:
                query = query.filter(SalesOrder.payment_state == payment_state)
            if min_amount_exclusive is not None:
                query = query.filter(SalesOrder.total_amount > Decimal(str(min_amount_exclusive)))
            if region:
                query = query.join(Customer, SalesOrder.customer_id == Customer.id).filter(
                    Customer.contact_address.contains(str(region))
                )

            pairs = [(item, order) for item, order in query.all()]

            # 汇总采用订单总额，分组明细按订单行聚合。
            order_totals = {order.id: order.total_amount or Decimal("0") for _, order in pairs}
            summary_total = sum(order_totals.values())

            if group_by == "product":
                product_stats: dict[str, dict] = {}
                zero = Decimal("0")
                for item, order in pairs:
                    key = item.product_name or f"产品{item.id}"
                    entry = product_stats.setdefault(
                        key,
                        {"product_name": key, "quantity": zero, "amount": zero},
                    )
                    entry["quantity"] += item.quantity or zero
                    entry["amount"] += item.amount or zero

                return {
                    "success": True,
                    "data": [
                        {
                            "product_name": key,
                            "quantity": float(entry["quantity"]),
                            "amount": float(entry["amount"]),
                        }
                        for key, entry in sorted(product_stats.items())
                    ],
                    "summary": {
                        "total_quantity": float(sum(e["quantity"] for e in product_stats.values())),
                        "total_amount": float(summary_total),
                    },
                }

            if group_by in {"customer", "date"}:
                by_customer = group_by == "customer"
                field = "customer_name" if by_customer else "date"
                stats: dict[str, dict] = {}
                zero = Decimal("0")
                for item, order in pairs:
                    if by_customer:
                        key = order.customer_name or f"客户{order.customer_id or order.id}"
                    else:
                        key = (
                            order.created_at.strftime("%Y-%m-%d") if order.created_at else "unknown"
                        )
                    entry = stats.setdefault(key, {"order_ids": set(), "amount": zero})
                    entry["order_ids"].add(order.id)
                    entry["amount"] += item.amount or zero

                return {
                    "success": True,
                    "data": [
                        {
                            field: key,
                            "order_count": len(entry["order_ids"]),
                            "amount": float(entry["amount"]),
                        }
                        for key, entry in sorted(stats.items())
                    ],
                    "summary": {
                        ("total_customers" if by_customer else "total_days"): len(stats),
                        "total_amount": float(summary_total),
                    },
                }

            return {"success": False, "message": f"不支持的 group_by: {group_by}"}

    def _get_sales_report_from_shipments(
        self,
        start_date: datetime | None,
        end_date: datetime | None,
        group_by: str,
        customer_id: int | None,
    ) -> dict[str, Any]:
        """读取历史发货记录的销售汇总。"""
        with get_db() as db:
            query = db.query(ShipmentRecord, func.count(ShipmentRecord.id).label("record_count"))

            if start_date:
                query = query.filter(ShipmentRecord.created_at >= start_date)
            if end_date:
                query = query.filter(ShipmentRecord.created_at <= end_date)
            if customer_id:
                query = query.filter(ShipmentRecord.unit_id == customer_id)

            records = query.group_by(ShipmentRecord.id).all()

            if group_by == "product":
                product_stats: dict[str, dict[str, Any]] = {}
                for record, count in records:
                    key = record.product_name or f"产品{record.id}"
                    if key not in product_stats:
                        product_stats[key] = {"product_name": key, "quantity": 0, "amount": 0}
                    product_stats[key]["quantity"] += float(record.quantity_kg or 0)
                    product_stats[key]["amount"] += float(record.amount or 0)

                return {
                    "success": True,
                    "data": list(product_stats.values()),
                    "summary": {
                        "total_quantity": sum(p["quantity"] for p in product_stats.values()),
                        "total_amount": sum(p["amount"] for p in product_stats.values()),
                    },
                }

            elif group_by == "customer":
                customer_stats: dict[str, dict[str, Any]] = {}
                for record, count in records:
                    key = record.purchase_unit or f"客户{record.unit_id or record.id}"
                    if key not in customer_stats:
                        customer_stats[key] = {"customer_name": key, "order_count": 0, "amount": 0}
                    customer_stats[key]["order_count"] += 1
                    customer_stats[key]["amount"] += float(record.amount or 0)

                return {
                    "success": True,
                    "data": list(customer_stats.values()),
                    "summary": {
                        "total_customers": len(customer_stats),
                        "total_amount": sum(c["amount"] for c in customer_stats.values()),
                    },
                }

            elif group_by == "date":
                date_stats: dict[str, dict[str, Any]] = {}
                for record, count in records:
                    date_key = (
                        record.created_at.strftime("%Y-%m-%d") if record.created_at else "unknown"
                    )
                    if date_key not in date_stats:
                        date_stats[date_key] = {"date": date_key, "order_count": 0, "amount": 0}
                    date_stats[date_key]["order_count"] += 1
                    date_stats[date_key]["amount"] += float(record.amount or 0)

                return {
                    "success": True,
                    "data": list(date_stats.values()),
                    "summary": {
                        "total_days": len(date_stats),
                        "total_amount": sum(d["amount"] for d in date_stats.values()),
                    },
                }

            return {"success": True, "data": [], "summary": {}}

    def get_inventory_report(
        self,
        warehouse_id: int | None = None,
        category: str | None = None,
        model_number: str | None = None,
    ) -> dict[str, Any]:
        with get_db() as db:
            query = db.query(InventoryLedger, Product).join(Product)

            if warehouse_id:
                query = query.filter(InventoryLedger.warehouse_id == warehouse_id)
            if category:
                query = query.filter(Product.category == category)
            if model_number:
                query = query.filter(Product.model_number == model_number)

            ledgers = query.all()

            product_inventory: dict[int, dict[str, Any]] = {}
            for ledger, product in ledgers:
                key = product.id
                if key not in product_inventory:
                    product_inventory[key] = {
                        "product_id": product.id,
                        "product_name": product.name,
                        "model_number": product.model_number,
                        "category": product.category,
                        "total_quantity": 0,
                        "available_quantity": 0,
                        "reserved_quantity": 0,
                        "warehouse_name": ledger.warehouse.name if ledger.warehouse else None,
                    }
                product_inventory[key]["total_quantity"] += float(ledger.quantity or 0)
                product_inventory[key]["available_quantity"] += float(
                    ledger.available_quantity or 0
                )
                product_inventory[key]["reserved_quantity"] += float(ledger.reserved_quantity or 0)

            return {
                "success": True,
                "data": list(product_inventory.values()),
                "summary": {
                    "total_products": len(product_inventory),
                    "total_quantity": sum(p["total_quantity"] for p in product_inventory.values()),
                    "total_available": sum(
                        p["available_quantity"] for p in product_inventory.values()
                    ),
                },
            }

    def get_purchase_report(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        group_by: str = "supplier",
    ) -> dict[str, Any]:
        with get_db() as db:
            query = db.query(PurchaseOrder)

            if start_date:
                query = query.filter(PurchaseOrder.order_date >= start_date)
            if end_date:
                query = query.filter(PurchaseOrder.order_date <= end_date)

            orders = query.all()

            if group_by == "supplier":
                supplier_stats: dict[str, dict[str, Any]] = {}
                for order in orders:
                    key = order.supplier.name if order.supplier else f"供应商{order.supplier_id}"
                    if key not in supplier_stats:
                        supplier_stats[key] = {
                            "supplier_name": key,
                            "order_count": 0,
                            "total_amount": 0,
                            "paid_amount": 0,
                        }
                    supplier_stats[key]["order_count"] += 1
                    supplier_stats[key]["total_amount"] += float(order.total_amount or 0)
                    supplier_stats[key]["paid_amount"] += float(order.paid_amount or 0)

                return {
                    "success": True,
                    "data": list(supplier_stats.values()),
                    "summary": {
                        "total_suppliers": len(supplier_stats),
                        "total_amount": sum(s["total_amount"] for s in supplier_stats.values()),
                    },
                }

            elif group_by == "status":
                status_stats: dict[str, dict[str, Any]] = {}
                for order in orders:
                    key = order.status or "unknown"
                    if key not in status_stats:
                        status_stats[key] = {"status": key, "order_count": 0, "total_amount": 0}
                    status_stats[key]["order_count"] += 1
                    status_stats[key]["total_amount"] += float(order.total_amount or 0)

                return {"success": True, "data": list(status_stats.values())}

            elif group_by == "date":
                date_stats: dict[str, dict[str, Any]] = {}
                for order in orders:
                    date_key = (
                        order.order_date.strftime("%Y-%m-%d") if order.order_date else "unknown"
                    )
                    if date_key not in date_stats:
                        date_stats[date_key] = {
                            "date": date_key,
                            "order_count": 0,
                            "total_amount": 0,
                        }
                    date_stats[date_key]["order_count"] += 1
                    date_stats[date_key]["total_amount"] += float(order.total_amount or 0)

                return {"success": True, "data": list(date_stats.values())}

            return {"success": True, "data": []}

    def get_inventory_transaction_report(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        transaction_type: str | None = None,
        product_id: int | None = None,
    ) -> dict[str, Any]:
        with get_db() as db:
            query = db.query(InventoryTransaction)

            if start_date:
                query = query.filter(InventoryTransaction.transaction_date >= start_date)
            if end_date:
                query = query.filter(InventoryTransaction.transaction_date <= end_date)
            if transaction_type:
                query = query.filter(InventoryTransaction.transaction_type == transaction_type)
            if product_id:
                query = query.filter(InventoryTransaction.product_id == product_id)

            transactions = (
                query.order_by(InventoryTransaction.transaction_date.desc()).limit(1000).all()
            )

            result = []
            for t in transactions:
                result.append(
                    {
                        "id": t.id,
                        "transaction_type": t.transaction_type,
                        "product_name": t.product.name if t.product else None,
                        "warehouse_name": t.warehouse.name if t.warehouse else None,
                        "quantity": self._decimal_to_float(t.quantity),
                        "before_quantity": self._decimal_to_float(t.before_quantity),
                        "after_quantity": self._decimal_to_float(t.after_quantity),
                        "unit_price": self._decimal_to_float(t.unit_price),
                        "total_amount": self._decimal_to_float(t.total_amount),
                        "reference_type": t.reference_type,
                        "transaction_date": (
                            t.transaction_date.isoformat() if t.transaction_date else None
                        ),
                        "operator": t.operator,
                        "remark": t.remark,
                    }
                )

            return {"success": True, "data": result, "count": len(result)}

    def get_dashboard_summary(self) -> dict[str, Any]:
        with get_db() as db:
            today = datetime.now()
            month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            product_count = db.query(func.count(Product.id)).scalar() or 0
            supplier_count = (
                db.query(func.count(Supplier.id)).filter(Supplier.status == "active").scalar() or 0
            )

            month_sales = (
                db.query(func.count(SalesOrder.id), func.sum(SalesOrder.total_amount))
                .filter(SalesOrder.created_at >= month_start)
                .first()
            )

            month_purchases = (
                db.query(func.count(PurchaseOrder.id), func.sum(PurchaseOrder.total_amount))
                .filter(PurchaseOrder.order_date >= month_start)
                .first()
            )

            low_stock_count = (
                db.query(func.count(InventoryLedger.id))
                .filter(InventoryLedger.available_quantity <= 0)
                .scalar()
                or 0
            )

            pending_orders = (
                db.query(func.count(PurchaseOrder.id))
                .filter(PurchaseOrder.status.in_(["draft", "approved"]))
                .scalar()
                or 0
            )

            return {
                "success": True,
                "data": {
                    "product_count": product_count,
                    "supplier_count": supplier_count,
                    "monthly_sales": {
                        "order_count": month_sales[0] or 0,
                        "total_amount": self._decimal_to_float(month_sales[1]),
                    },
                    "monthly_purchases": {
                        "order_count": month_purchases[0] or 0,
                        "total_amount": self._decimal_to_float(month_purchases[1]),
                    },
                    "alerts": {"low_stock": low_stock_count, "pending_orders": pending_orders},
                },
            }

    def export_to_excel(
        self, report_type: str, data: list[dict[str, Any]], filename: str
    ) -> dict[str, Any]:
        return export_report_to_excel(report_type, data, filename)


# NEURO-DDD: 为 Services 层类添加 instrumentation
from app.neuro_bus.neuro_service_instrumentation import instrument_service_layer_class

instrument_service_layer_class(ReportService, "app.domain.shared_services.report_service")
