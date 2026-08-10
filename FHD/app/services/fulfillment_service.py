"""履行 / 预留 / backorder / return 模块（ODOO-W1-03）。

履行维度**仅**由 ``ordered / reserved / delivered / returned`` 四类数量派生，全部落于
``inventory_transactions``（stock moves，复用既有表，不新建 move 表）+
``inventory_ledger.reserved_quantity``；**不读取订单金额**。

- ``reserve``：按明细预留，写 ``reserve`` 流水，预留量落于 ledger.reserved_quantity。
- ``deliver``：真实扣减库存；``qty < ordered - delivered`` 记为 **partial** 交付并触发
  **backorder**；``qty > 剩余订购量`` 超量被拒。
- ``return_sale``：生成反向 move（``return`` 流水）并回补库存。

所有写操作租户作用域（依赖全局 tenant filter 自动打标）且幂等（可选 idempotency_key）。
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.db.models import InventoryTransaction, SalesOrder, SalesOrderItem
from app.db.session import get_db
from app.services.inventory_service import InventoryService
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _effective_ordered(item: SalesOrderItem) -> Decimal:
    """订购量：优先明细的 ordered_quantity，未设置时回退到 quantity。"""
    ordered = _to_decimal(getattr(item, "ordered_quantity", None))
    if ordered <= 0:
        ordered = _to_decimal(getattr(item, "quantity", None))
    return ordered


class FulfillmentService:
    """履行服务：预留、交付（partial/backorder）、退货（return）。"""

    def __init__(self, inventory_service: InventoryService | None = None) -> None:
        self.inventory = inventory_service or InventoryService()

    # ── 私有辅助 ────────────────────────────────────────────────

    def _get_order_and_item(
        self, db: Any, order_id: Any, item_id: Any
    ) -> tuple[SalesOrder | None, SalesOrderItem | None, str | None]:
        order = db.query(SalesOrder).filter(SalesOrder.id == int(order_id)).first()
        if order is None:
            return None, None, "销售订单不存在"
        item = db.query(SalesOrderItem).filter(SalesOrderItem.id == int(item_id)).first()
        if item is None:
            return order, None, "订单明细不存在"
        if item.order_id != order.id:
            return order, item, "订单明细不属于该订单"
        return order, item, None

    def _idempotency_done(self, db: Any, item_id: Any, op: str, key: str | None) -> bool:
        if not key:
            return False
        marker = f"idempotency:{op}:{key}"
        existing = (
            db.query(InventoryTransaction)
            .filter(
                InventoryTransaction.sales_order_item_id == int(item_id),
                InventoryTransaction.remark.like(f"{marker}%"),
            )
            .first()
        )
        return existing is not None

    def _mark(self, remark: str | None, op: str, key: str | None) -> str | None:
        if not key:
            return remark
        marker = f"idempotency:{op}:{key}"
        return f"{marker} | {remark}" if remark else marker

    def _item_fulfillment(self, item: SalesOrderItem) -> dict[str, Any]:
        ordered = _effective_ordered(item)
        reserved = _to_decimal(item.reserved_quantity)
        delivered = _to_decimal(item.delivered_quantity)
        returned = _to_decimal(item.returned_quantity)
        backorder_qty = max(Decimal("0"), ordered - delivered)
        return {
            "item_id": item.id,
            "order_id": item.order_id,
            "product_id": item.product_id,
            "ordered_quantity": float(ordered),
            "reserved_quantity": float(reserved),
            "delivered_quantity": float(delivered),
            "returned_quantity": float(returned),
            "backorder_quantity": float(backorder_qty),
        }

    # ── backorder 子单 ──────────────────────────────────────────

    def _backorder_child(self, db: Any, order_id: Any) -> SalesOrder | None:
        """返回该订单的唯一 backorder 子单（backorder_of_id 指向父单），不存在返回 None。"""
        return (
            db.query(SalesOrder)
            .filter(SalesOrder.backorder_of_id == int(order_id))
            .order_by(SalesOrder.id.asc())
            .first()
        )

    @staticmethod
    def _source_marker(item_id: Any) -> str:
        """backorder 子单明细的来源标记（唯一标识父单明细）。"""
        return f"backorder source_item_id={int(item_id)}"

    def _find_child_item(
        self, child: SalesOrder, item_id: Any
    ) -> SalesOrderItem | None:
        """按来源标记在子单中定位对应父单明细的补货明细（替代 child.items[0] 假设）。"""
        marker = self._source_marker(item_id)
        for child_item in child.items:
            if child_item.remark and marker in child_item.remark:
                return child_item
        return None

    def _create_child_item(
        self, child: SalesOrder, item: SalesOrderItem, outstanding: Decimal
    ) -> SalesOrderItem:
        """在子单中为父单明细创建补货明细（打来源标记）。"""
        child_item = SalesOrderItem(
            order_id=child.id,
            product_id=item.product_id,
            product_name=item.product_name,
            specification=item.specification,
            quantity=outstanding,
            unit=item.unit or "个",
            unit_price=item.unit_price,
            amount=Decimal("0"),
            ordered_quantity=outstanding,
            reserved_quantity=Decimal("0"),
            delivered_quantity=Decimal("0"),
            returned_quantity=Decimal("0"),
            invoiced_quantity=Decimal("0"),
            status="pending",
            remark=self._source_marker(item.id),
            created_at=datetime.now(),
        )
        return child_item

    def _sync_backorder(
        self, db: Any, order: SalesOrder, item: SalesOrderItem, outstanding: Decimal
    ) -> SalesOrder | None:
        """同步父单的唯一 backorder 子单（幂等、确定性、支持多明细）。

        - ``outstanding > 0``：首次部分交付创建子单（order_no 确定性派生），
          并按来源标记（``source_item_id={item.id}``）定位/创建子单明细，
          使父单多明细各自映射到独立补货明细，而非统一落到 child.items[0]。
        - ``outstanding <= 0``：终次交付把对应子单明细未交付量归零（解析），
          若暂无子单或无对应明细则无操作。
        """
        child = self._backorder_child(db, order.id)
        if outstanding <= 0:
            if child is not None:
                child_item = self._find_child_item(child, item.id)
                if child_item is not None:
                    child_item.quantity = outstanding
                    child_item.ordered_quantity = outstanding
            return child
        if child is None:
            child = SalesOrder(
                order_no=f"{order.order_no}-BO",
                customer_id=order.customer_id,
                customer_name=order.customer_name,
                state="confirmed",
                status="confirmed",
                total_amount=Decimal("0"),
                paid_amount=Decimal("0"),
                currency=order.currency or "CNY",
                backorder_of_id=order.id,
                created_at=datetime.now(),
            )
            db.add(child)
            db.flush()
            db.add(self._create_child_item(child, item, outstanding))
        else:
            child_item = self._find_child_item(child, item.id)
            if child_item is None:
                db.add(self._create_child_item(child, item, outstanding))
            else:
                child_item.quantity = outstanding
                child_item.ordered_quantity = outstanding
        return child

    def get_backorder(self, order_id: int) -> dict[str, Any]:
        """返回父单的 backorder 子单视图（含关联、明细与剩余未交付量）。

        ``remaining_quantity`` 由子单全部明细的 ``ordered_quantity`` 汇总，
        兼容多明细子单（而非仅取 child.items[0]）。
        """
        with get_db() as db:
            child = self._backorder_child(db, order_id)
            if child is None:
                return {"success": True, "order_id": int(order_id), "backorder": None}
            remaining = sum(
                (_to_decimal(ci.ordered_quantity) for ci in child.items),
                Decimal("0"),
            )
            items = [
                {
                    "item_id": ci.id,
                    "product_id": ci.product_id,
                    "product_name": ci.product_name,
                    "ordered_quantity": float(_to_decimal(ci.ordered_quantity)),
                    "source_item_id": (
                        int(ci.remark.split("source_item_id=")[1].strip())
                        if ci.remark and "source_item_id=" in ci.remark
                        else None
                    ),
                }
                for ci in child.items
            ]
            return {
                "success": True,
                "order_id": int(order_id),
                "backorder": {
                    "order_id": child.id,
                    "order_no": child.order_no,
                    "backorder_of_id": child.backorder_of_id,
                    "remaining_quantity": float(remaining),
                    "items": items,
                },
            }

    # ── 预留 ────────────────────────────────────────────────────

    def reserve(
        self,
        order_id: int,
        item_id: int,
        quantity: float,
        *,
        warehouse_id: int,
        product_id: int | None = None,
        batch_no: str | None = None,
        location_id: int | None = None,
        operator: str | None = None,
        remark: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        with get_db() as db:
            try:
                order, item, err = self._get_order_and_item(db, order_id, item_id)
                if err:
                    return {"success": False, "message": err}
                if self._idempotency_done(db, item_id, "reserve", idempotency_key):
                    return {
                        "success": True,
                        "message": "预留已处理（幂等）",
                        "data": self._item_fulfillment(item),
                        "idempotent": True,
                    }
                q = _to_decimal(quantity)
                if q <= 0:
                    return {"success": False, "message": "预留数量必须大于 0"}
                ordered = _effective_ordered(item)
                reserved = _to_decimal(item.reserved_quantity)
                if reserved + q > ordered:
                    return {
                        "success": False,
                        "message": f"预留超量被拒：已预留 {reserved}，本次 {q}，订购 {ordered}",
                    }
                pid = product_id or item.product_id
                if not pid:
                    return {"success": False, "message": "缺少产品"}
                inv = self.inventory.reserve_for_order(
                    product_id=pid,
                    warehouse_id=warehouse_id,
                    quantity=q,
                    sales_order_id=order.id,
                    sales_order_item_id=item.id,
                    batch_no=batch_no,
                    location_id=location_id,
                    operator=operator,
                    remark=self._mark(remark, "reserve", idempotency_key),
                    db=db,
                )
                if not inv["success"]:
                    return inv
                item.reserved_quantity = reserved + q
                db.commit()
                db.refresh(item)
                return {
                    "success": True,
                    "message": "预留成功",
                    "data": self._item_fulfillment(item),
                }
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                logger.error("履行预留失败: %s", e)
                return {"success": False, "message": str(e)}

    # ── 交付（partial / backorder）──────────────────────────────

    def deliver(
        self,
        order_id: int,
        item_id: int,
        quantity: float,
        *,
        warehouse_id: int,
        product_id: int | None = None,
        batch_no: str | None = None,
        location_id: int | None = None,
        operator: str | None = None,
        remark: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        with get_db() as db:
            try:
                order, item, err = self._get_order_and_item(db, order_id, item_id)
                if err:
                    return {"success": False, "message": err}
                if self._idempotency_done(db, item_id, "deliver", idempotency_key):
                    return {
                        "success": True,
                        "message": "交付已处理（幂等）",
                        "data": self._item_fulfillment(item),
                        "idempotent": True,
                    }
                q = _to_decimal(quantity)
                if q <= 0:
                    return {"success": False, "message": "交付数量必须大于 0"}
                ordered = _effective_ordered(item)
                delivered = _to_decimal(item.delivered_quantity)
                if delivered + q > ordered:
                    over = delivered + q - ordered
                    return {
                        "success": False,
                        "message": f"交付超量被拒：已交付 {delivered}，本次 {q}，订购 {ordered}，超出 {over}",
                    }
                pid = product_id or item.product_id
                if not pid:
                    return {"success": False, "message": "缺少产品"}
                inv = self.inventory.deduct_for_order(
                    product_id=pid,
                    warehouse_id=warehouse_id,
                    quantity=q,
                    sales_order_id=order.id,
                    sales_order_item_id=item.id,
                    batch_no=batch_no,
                    location_id=location_id,
                    operator=operator,
                    remark=self._mark(remark, "deliver", idempotency_key),
                    db=db,
                )
                if not inv["success"]:
                    return inv
                item.delivered_quantity = delivered + q
                # 交付消耗对应预留
                item.reserved_quantity = max(Decimal("0"), _to_decimal(item.reserved_quantity) - q)
                new_delivered = delivered + q
                partial = new_delivered < ordered
                backorder_qty = max(Decimal("0"), ordered - new_delivered)
                child = self._sync_backorder(db, order, item, backorder_qty)
                db.commit()
                db.refresh(item)
                return {
                    "success": True,
                    "message": "部分交付并触发 backorder" if partial else "交付完成",
                    "data": {
                        **self._item_fulfillment(item),
                        "partial": partial,
                        "backorder": partial,
                        "backorder_quantity": float(backorder_qty),
                        "backorder_order_id": child.id if child is not None else None,
                        "backorder_order_no": child.order_no if child is not None else None,
                        "fulfillment": order.fulfillment_state(),
                    },
                }
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                logger.error("履行交付失败: %s", e)
                return {"success": False, "message": str(e)}

    # ── 退货（return）───────────────────────────────────────────

    def return_sale(
        self,
        order_id: int,
        item_id: int,
        quantity: float,
        *,
        warehouse_id: int,
        product_id: int | None = None,
        batch_no: str | None = None,
        location_id: int | None = None,
        operator: str | None = None,
        remark: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        with get_db() as db:
            try:
                order, item, err = self._get_order_and_item(db, order_id, item_id)
                if err:
                    return {"success": False, "message": err}
                if self._idempotency_done(db, item_id, "return", idempotency_key):
                    return {
                        "success": True,
                        "message": "退货已处理（幂等）",
                        "data": self._item_fulfillment(item),
                        "idempotent": True,
                    }
                q = _to_decimal(quantity)
                if q <= 0:
                    return {"success": False, "message": "退货数量必须大于 0"}
                delivered = _to_decimal(item.delivered_quantity)
                returned = _to_decimal(item.returned_quantity)
                if returned + q > delivered:
                    return {
                        "success": False,
                        "message": f"退货超过已交付：已交付 {delivered}，已退 {returned}，本次 {q}",
                    }
                pid = product_id or item.product_id
                if not pid:
                    return {"success": False, "message": "缺少产品"}
                inv = self.inventory.restock_for_order(
                    product_id=pid,
                    warehouse_id=warehouse_id,
                    quantity=q,
                    sales_order_id=order.id,
                    sales_order_item_id=item.id,
                    batch_no=batch_no,
                    location_id=location_id,
                    operator=operator,
                    remark=self._mark(remark, "return", idempotency_key),
                    db=db,
                )
                if not inv["success"]:
                    return inv
                item.returned_quantity = returned + q
                db.commit()
                db.refresh(item)
                return {
                    "success": True,
                    "message": "退货成功，库存已回补",
                    "data": self._item_fulfillment(item),
                }
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                logger.error("履行退货失败: %s", e)
                return {"success": False, "message": str(e)}

    # ── 履行派生口径 ────────────────────────────────────────────

    def fulfillment_state(self, order_id: int) -> dict[str, Any]:
        """履行状态仅由四类数量派生（不读金额）。"""
        with get_db() as db:
            order = db.query(SalesOrder).filter(SalesOrder.id == int(order_id)).first()
            if order is None:
                return {"success": False, "message": "销售订单不存在"}
            return {"success": True, "order_id": order.id, "state": order.fulfillment_state()}

    def get_fulfillment(self, order_id: int) -> dict[str, Any]:
        """返回订单的履行视图（按明细聚合四类数量）。"""
        with get_db() as db:
            order = db.query(SalesOrder).filter(SalesOrder.id == int(order_id)).first()
            if order is None:
                return {"success": False, "message": "销售订单不存在"}
            return {
                "success": True,
                "data": {
                    "order_id": order.id,
                    "order_no": order.order_no,
                    "fulfillment": order.fulfillment_state(),
                    "items": [self._item_fulfillment(i) for i in order.items],
                },
            }


__all__ = ["FulfillmentService", "_effective_ordered"]
