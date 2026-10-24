"""Order queries and quote creation with caller-owned or locally owned sessions."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import SalesOrder, SalesOrderItem

from .contracts import SessionFactory
from .idempotency import CLOSED_LOOP_FP_PREFIX


def generate_order_no() -> str:
    return f"SO{datetime.now().strftime('%Y%m%d%H%M%S')}"


class SalesQuotes:
    def __init__(
        self,
        sessions: SessionFactory,
        order_number: Callable[[], str],
        decimal: Callable[[Any], Decimal],
    ) -> None:
        self._sessions = sessions
        self._order_number = order_number
        self._decimal = decimal

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
        with self._sessions() as db:
            q = db.query(SalesOrder)
            if status:
                q = q.filter(SalesOrder.status == status)
            if customer_id:
                q = q.filter(SalesOrder.customer_id == customer_id)
            if customer_name:
                q = q.filter(SalesOrder.customer_name == customer_name)
            if keyword:
                like = f"%{keyword}%"
                q = q.filter(SalesOrder.order_no.like(like) | SalesOrder.customer_name.like(like))
            total = q.count()
            orders = (
                q.order_by(SalesOrder.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
            )
            return {
                "success": True,
                "data": [o.to_dict() for o in orders],
                "total": total,
                "page": page,
                "per_page": per_page,
            }

    def quote(self, data: dict[str, Any], *, db: Session | None = None) -> dict[str, Any]:
        """创建幂等报价；传入 db 时仅 flush/refresh，缺省时使用自有会话并提交。"""
        from app.application.sales_quote_inputs import validated_quote_request

        try:
            items_data = validated_quote_request(data)
        except ValueError as exc:
            return {"success": False, "message": str(exc)}
        idempotency_key = str(data.get("idempotency_key") or "").strip() or None
        idem_marker = f"idempotency:sales_quote:{idempotency_key}" if idempotency_key else None
        owned = db is None
        cm = self._sessions() if db is None else nullcontext(db)
        with cm as ctx:
            if idem_marker:
                existing = (
                    ctx.query(SalesOrder)
                    .filter(
                        or_(
                            SalesOrder.remark == idem_marker,
                            SalesOrder.remark.startswith(
                                idem_marker + "\n" + CLOSED_LOOP_FP_PREFIX + ":",
                                autoescape=True,
                                escape="\\",
                            ),
                        )
                    )
                    .order_by(SalesOrder.id.desc())
                    .first()
                )
                if existing is not None:
                    return {
                        "success": True,
                        "message": f"报价单已存在（幂等）: {existing.order_no}",
                        "data": existing.to_dict(),
                        "idempotent": True,
                    }
            from app.application.sales_quote_references import resolve_quote_references

            try:
                customer, resolved_items = resolve_quote_references(ctx, data, items_data)
            except (ValueError, TypeError) as exc:
                return {"success": False, "message": str(exc)}
            if customer.id is None:
                ctx.add(customer)
                ctx.flush()
            total_amount = Decimal("0")
            order_no = data.get("order_no") or self._order_number()
            order = SalesOrder(
                order_no=order_no,
                customer_id=customer.id,
                customer_name=customer.customer_name,
                state="quote",
                status="quote",
                quote_date=data.get("quote_date", datetime.now().date()),
                total_amount=Decimal("0"),
                paid_amount=Decimal("0"),
                currency=data.get("currency", "CNY"),
                remark=idem_marker or data.get("remark"),
                created_at=datetime.now(),
            )
            ctx.add(order)
            ctx.flush()
            for item_data, product in resolved_items:
                product_id = product.id if product is not None else None
                quantity = self._decimal(item_data.get("quantity", "0"))
                unit_price = self._decimal(item_data.get("unit_price", "0"))
                amount = quantity * unit_price
                total_amount += amount
                ctx.add(
                    SalesOrderItem(
                        order_id=order.id,
                        product_id=product_id,
                        product_name=product.name if product else item_data.get("product_name"),
                        specification=item_data.get("specification"),
                        quantity=quantity,
                        unit=item_data.get("unit", "个"),
                        unit_price=unit_price,
                        amount=amount,
                        ordered_quantity=quantity,
                        delivered_quantity=Decimal("0"),
                        returned_quantity=Decimal("0"),
                        invoiced_quantity=Decimal("0"),
                        status="pending",
                        remark=item_data.get("remark"),
                        created_at=datetime.now(),
                    )
                )
            order.total_amount = total_amount
            ctx.flush()
            if owned:
                ctx.commit()
            ctx.refresh(order)
            return {
                "success": True,
                "message": f"报价单已创建: {order.order_no}",
                "data": order.to_dict(),
            }
