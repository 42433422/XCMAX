"""
销售应用服务（Sales-to-Payment 闭环）

吸收 Odoo 18 sale.order 状态机：报价(quote) -> 确认(confirmed) -> 发货(delivered)
-> 开票(invoiced) -> 收款(paid)。本模块是 `sales` 能力工具的只读/受控写入执行器。
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import or_

from app.db.models import Customer, Product, SalesOrder, SalesOrderItem
from app.db.models.sales import SALES_ORDER_STATUS_FLOW
from app.db.session import get_db
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


class SalesAppService:
    """销售应用服务：报价、确认、发货、开票、收款与查询。"""

    # ── 查询 ────────────────────────────────────────────────────

    def query(
        self,
        status: str | None = None,
        customer_id: int | None = None,
        customer_name: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """按状态/客户/关键字查询销售订单列表。"""
        with get_db() as db:
            q = db.query(SalesOrder)
            if status:
                q = q.filter(SalesOrder.status == status)
            if customer_id:
                q = q.filter(SalesOrder.customer_id == customer_id)
            if customer_name:
                q = q.filter(SalesOrder.customer_name == customer_name)
            if keyword:
                like = f"%{keyword}%"
                q = q.filter(
                    or_(
                        SalesOrder.order_no.like(like),
                        SalesOrder.customer_name.like(like),
                    )
                )
            total = q.count()
            orders = (
                q.order_by(SalesOrder.id.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
                .all()
            )
            return {
                "success": True,
                "data": [o.to_dict() for o in orders],
                "total": total,
                "page": page,
                "per_page": per_page,
            }

    # ── 报价创建 ────────────────────────────────────────────────

    def quote(self, data: dict[str, Any]) -> dict[str, Any]:
        """创建报价单（status=quote），明细项由 items 提供。"""
        customer_id = data.get("customer_id")
        items_data = data.get("items") or []
        if not customer_id:
            return {"success": False, "message": "缺少 customer_id"}
        if not isinstance(items_data, list) or not items_data:
            return {"success": False, "message": "缺少 items 明细"}

        with get_db() as db:
            customer = db.query(Customer).filter(Customer.id == int(customer_id)).first()
            if customer is None:
                return {"success": False, "message": f"客户不存在: customer_id={customer_id}"}

            total_amount = 0.0
            order_no = data.get("order_no") or self._generate_order_no()
            order = SalesOrder(
                order_no=order_no,
                customer_id=customer.id,
                customer_name=customer.customer_name,
                status="quote",
                quote_date=data.get("quote_date", datetime.now().date()),
                total_amount=Decimal("0"),
                paid_amount=Decimal("0"),
                currency=data.get("currency", "CNY"),
                remark=data.get("remark"),
                created_at=datetime.now(),
            )
            db.add(order)
            db.flush()

            for item_data in items_data:
                product_id = item_data.get("product_id")
                product = (
                    db.query(Product).filter(Product.id == product_id).first()
                    if product_id
                    else None
                )
                quantity = _to_float(item_data.get("quantity", 0))
                unit_price = _to_float(item_data.get("unit_price", 0))
                amount = quantity * unit_price
                total_amount += amount
                db.add(
                    SalesOrderItem(
                        order_id=order.id,
                        product_id=product_id,
                        product_name=(
                            product.name if product else item_data.get("product_name")
                        ),
                        specification=item_data.get("specification"),
                        quantity=Decimal(str(quantity)),
                        unit=item_data.get("unit", "个"),
                        unit_price=Decimal(str(unit_price)),
                        amount=Decimal(str(amount)),
                        delivered_quantity=Decimal("0"),
                        invoiced_quantity=Decimal("0"),
                        status="pending",
                        remark=item_data.get("remark"),
                        created_at=datetime.now(),
                    )
                )

            order.total_amount = Decimal(str(total_amount))
            db.commit()
            db.refresh(order)
            return {
                "success": True,
                "message": f"报价单已创建: {order.order_no}",
                "data": order.to_dict(),
            }

    # ── 状态推进 ────────────────────────────────────────────────

    def _advance(self, order_id: int, new_status: str) -> dict[str, Any]:
        with get_db() as db:
            order = db.query(SalesOrder).filter(SalesOrder.id == int(order_id)).first()
            if order is None:
                return {"success": False, "message": f"销售订单不存在: order_id={order_id}"}
            try:
                order.advance(new_status)
            except ValueError as exc:
                return {"success": False, "message": str(exc)}
            if new_status == "confirmed":
                order.confirm_date = datetime.now().date()
            db.commit()
            db.refresh(order)
            return {
                "success": True,
                "message": f"销售订单 {order.order_no} 已推进至 {new_status}",
                "data": order.to_dict(),
            }

    def confirm(self, order_id: int) -> dict[str, Any]:
        return self._advance(order_id, "confirmed")

    def deliver(self, order_id: int) -> dict[str, Any]:
        return self._advance(order_id, "delivered")

    def invoice(self, order_id: int) -> dict[str, Any]:
        return self._advance(order_id, "invoiced")

    def payment(self, order_id: int, amount: float | None = None) -> dict[str, Any]:
        """登记收款；金额达到或超过总额时推进到 paid，否则记录部分收款。"""
        with get_db() as db:
            order = db.query(SalesOrder).filter(SalesOrder.id == int(order_id)).first()
            if order is None:
                return {"success": False, "message": f"销售订单不存在: order_id={order_id}"}
            pay_amount = _to_float(amount) if amount is not None else _to_float(order.total_amount)
            if pay_amount <= 0:
                return {"success": False, "message": "收款金额必须大于 0"}
            new_paid = _to_float(order.paid_amount) + pay_amount
            order.paid_amount = Decimal(str(new_paid))
            if new_paid >= _to_float(order.total_amount) - 1e-6:
                order.status = "paid"
            db.commit()
            db.refresh(order)
            return {
                "success": True,
                "message": (
                    f"已登记收款 ¥{pay_amount}，累计 ¥{new_paid}，订单状态 {order.status}"
                ),
                "data": order.to_dict(),
            }

    def cancel(self, order_id: int) -> dict[str, Any]:
        """取消订单（仅允许尚未进入收款/开票阶段）。"""
        with get_db() as db:
            order = db.query(SalesOrder).filter(SalesOrder.id == int(order_id)).first()
            if order is None:
                return {"success": False, "message": f"销售订单不存在: order_id={order_id}"}
            if order.status not in ("quote", "confirmed", "delivered"):
                return {
                    "success": False,
                    "message": f"订单状态 {order.status} 不允许取消",
                }
            order.status = "cancelled"
            db.commit()
            db.refresh(order)
            return {
                "success": True,
                "message": f"销售订单 {order.order_no} 已取消",
                "data": order.to_dict(),
            }

    # ── 工具内部 ────────────────────────────────────────────────

    @staticmethod
    def _generate_order_no() -> str:
        return f"SO{datetime.now().strftime('%Y%m%d%H%M%S')}"


__all__ = ["SalesAppService", "SALES_ORDER_STATUS_FLOW"]