"""Order reservation, deduction, and restock operations."""

from __future__ import annotations

import importlib
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, cast

from app.db.models.inventory import InventoryLedger, InventoryTransaction
from app.db.session import get_db
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger("app.domain.shared_services.inventory_service")


def _facade():
    return importlib.import_module("app.domain.shared_services.inventory_service")


def _order_quantity(value: Any) -> Decimal | None:
    try:
        quantity = Decimal(str(value))
        if (
            not quantity.is_finite() or quantity <= 0
            or quantity != quantity.quantize(Decimal("0.0001"))
        ):
            return None
        return quantity
    except (ValueError, TypeError, InvalidOperation):
        return None


def _order_ledger_cas(
    db: Any, ledger: InventoryLedger, *,
    physical_delta: Decimal, available_delta: Decimal, reserved_delta: Decimal,
    now: datetime,
) -> bool:
    """Same tenant-scoped stock row and observed version for all order movements."""
    physical = Decimal(str(ledger.quantity or 0))
    available = Decimal(str(ledger.available_quantity or 0))
    reserved = Decimal(str(ledger.reserved_quantity or 0))
    if physical != available + reserved or min(physical, available, reserved) < 0:
        return False
    new_physical = physical + physical_delta
    new_available = available + available_delta
    new_reserved = reserved + reserved_delta
    if (
        min(new_physical, new_available, new_reserved) < 0
        or new_physical != new_available + new_reserved
    ):
        return False
    changed = db.query(InventoryLedger).filter(
        InventoryLedger.id == ledger.id,
        InventoryLedger.tenant_id == ledger.tenant_id,
        InventoryLedger.quantity == physical,
        InventoryLedger.available_quantity == available,
        InventoryLedger.reserved_quantity == reserved,
    ).update(
        {
            InventoryLedger.quantity: new_physical,
            InventoryLedger.available_quantity: new_available,
            InventoryLedger.reserved_quantity: new_reserved,
            InventoryLedger.updated_at: now,
        },
        synchronize_session=False,
    )
    if changed != 1:
        return False
    db.refresh(ledger)
    return True


class InventoryOrdersMixin:
    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

    def reserve_for_order(
        self,
        product_id: int,
        warehouse_id: int,
        quantity: float,
        *,
        sales_order_id: int,
        sales_order_item_id: int,
        batch_no: str | None = None,
        location_id: int | None = None,
        operator: str | None = None,
        remark: str | None = None,
        db: Any = None,
    ) -> dict[str, Any]:
        """按单预留：将可用库存转入 reserved，并写一条 reserve 流水（stock move）。"""
        qty = _order_quantity(quantity)
        if qty is None:
            return {"success": False, "message": "预留数量必须大于 0"}

        def _run(db):
            ledger = (
                db.query(_facade().InventoryLedger)
                .filter(
                    _facade().InventoryLedger.product_id == product_id,
                    _facade().InventoryLedger.warehouse_id == warehouse_id,
                    _facade().InventoryLedger.batch_no == batch_no,
                    *(
                        (_facade().InventoryLedger.location_id == location_id,)
                        if location_id is not None else ()
                    ),
                )
                .first()
            )
            if not ledger:
                return {"success": False, "message": "库存台账记录不存在"}
            available = Decimal(str(ledger.available_quantity or 0))
            if available < qty:
                return {"success": False, "message": "可用库存不足，无法预留"}
            now = datetime.now()
            if not _order_ledger_cas(
                db, ledger, physical_delta=Decimal("0"),
                available_delta=-qty, reserved_delta=qty, now=now,
            ):
                return {"success": False, "message": "库存已并发变化或账实不一致，未预留"}
            db.flush()
            txn = _facade().InventoryTransaction(
                ledger_id=ledger.id,
                transaction_type="reserve",
                product_id=product_id,
                warehouse_id=warehouse_id,
                location_id=location_id,
                batch_no=batch_no,
                quantity=Decimal("0"),
                before_quantity=Decimal(str(ledger.quantity or 0)),
                after_quantity=Decimal(str(ledger.quantity or 0)),
                ordered_quantity=qty,
                delivered_quantity=Decimal("0"),
                sales_order_id=sales_order_id,
                sales_order_item_id=sales_order_item_id,
                reference_type="sale_reserve",
                reference_id=sales_order_id,
                transaction_date=now,
                operator=operator,
                remark=remark,
                created_at=now,
            )
            db.add(txn)
            return {
                "success": True,
                "ledger_id": ledger.id,
                "reserved_quantity": float(ledger.reserved_quantity),
                "available_quantity": float(ledger.available_quantity),
            }

        if db is not None:
            return cast("dict[str, Any]", _run(db))
        with _facade().get_db() as db:
            try:
                result = _run(db)
                if result["success"]:
                    db.commit()
                return cast("dict[str, Any]", result)
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                _facade().logger.error("按单预留失败: %s", e)
                return {"success": False, "message": str(e)}

    def deduct_for_order(
        self,
        product_id: int,
        warehouse_id: int,
        quantity: float,
        *,
        sales_order_id: int,
        sales_order_item_id: int,
        batch_no: str | None = None,
        location_id: int | None = None,
        operator: str | None = None,
        remark: str | None = None,
        db: Any = None,
    ) -> dict[str, Any]:
        """按单扣减：发货时真实扣减库存并消耗对应预留，写一条 out 流水（stock move）。"""
        qty = _order_quantity(quantity)
        if qty is None:
            return {"success": False, "message": "扣减数量必须大于 0"}

        def _run(db):
            ledger = (
                db.query(_facade().InventoryLedger)
                .filter(
                    _facade().InventoryLedger.product_id == product_id,
                    _facade().InventoryLedger.warehouse_id == warehouse_id,
                    _facade().InventoryLedger.batch_no == batch_no,
                    *(
                        (_facade().InventoryLedger.location_id == location_id,)
                        if location_id is not None else ()
                    ),
                )
                .first()
            )
            if not ledger:
                return {"success": False, "message": "库存台账记录不存在"}
            from app.db.models.sales import SalesOrderItem

            item = db.query(SalesOrderItem).filter(
                SalesOrderItem.id == sales_order_item_id,
                SalesOrderItem.order_id == sales_order_id,
                SalesOrderItem.product_id == product_id,
                SalesOrderItem.tenant_id == ledger.tenant_id,
            ).first()
            if item is None:
                return {"success": False, "message": "销售订单和出库明细身份不匹配"}
            item_reserved = Decimal(str(item.reserved_quantity or 0))
            consume_reserved = min(qty, item_reserved)
            if consume_reserved > 0:
                # A single sales item can currently aggregate multiple lots.
                # No lot-level outstanding balance exists: fail closed instead
                # of consuming another customer's reservation from this ledger.
                reserves = db.query(InventoryTransaction.ledger_id).filter(
                    InventoryTransaction.sales_order_item_id == item.id,
                    InventoryTransaction.transaction_type == "reserve",
                ).distinct().all()
                if not reserves or {r[0] for r in reserves} != {ledger.id}:
                    return {"success": False, "message": "无法唯一定位该订单预留库存，拒绝跨批次扣减"}
            free_needed = qty - consume_reserved
            available = Decimal(str(ledger.available_quantity or 0))
            reserved = Decimal(str(ledger.reserved_quantity or 0))
            if available < free_needed or reserved < consume_reserved:
                return {"success": False, "message": "本单预留或剩余可用库存不足，无法出库"}
            now = datetime.now()
            before = Decimal(str(ledger.quantity or 0))
            if not _order_ledger_cas(
                db, ledger, physical_delta=-qty, available_delta=-free_needed,
                reserved_delta=-consume_reserved, now=now,
            ):
                return {"success": False, "message": "库存已并发变化或账实不一致，未出库"}
            db.flush()
            txn = _facade().InventoryTransaction(
                ledger_id=ledger.id,
                transaction_type="out",
                product_id=product_id,
                warehouse_id=warehouse_id,
                location_id=location_id,
                batch_no=batch_no,
                quantity=-qty,
                before_quantity=before,
                after_quantity=Decimal(str(ledger.quantity)),
                ordered_quantity=qty,
                delivered_quantity=qty,
                sales_order_id=sales_order_id,
                sales_order_item_id=sales_order_item_id,
                reference_type="sale_delivery",
                reference_id=sales_order_id,
                transaction_date=now,
                operator=operator,
                remark=remark,
                created_at=now,
            )
            db.add(txn)
            return {
                "success": True,
                "ledger_id": ledger.id,
                "quantity": float(ledger.quantity),
                "available_quantity": float(ledger.available_quantity),
            }

        if db is not None:
            return cast("dict[str, Any]", _run(db))
        with _facade().get_db() as db:
            try:
                result = _run(db)
                if result["success"]:
                    db.commit()
                return cast("dict[str, Any]", result)
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                _facade().logger.error("按单扣减失败: %s", e)
                return {"success": False, "message": str(e)}

    def release_for_order(
        self,
        product_id: int,
        warehouse_id: int,
        quantity: float,
        *,
        sales_order_id: int,
        sales_order_item_id: int,
        batch_no: str | None = None,
        location_id: int | None = None,
        operator: str | None = None,
        remark: str | None = None,
        db: Any = None,
    ) -> dict[str, Any]:
        """取消未履约预留：把 reserved 退回 available，库存数量不变。"""
        qty = _order_quantity(quantity)
        if qty is None:
            return {"success": False, "message": "释放数量必须大于 0"}

        def _run(db):
            ledger = (
                db.query(InventoryLedger)
                .filter(
                    InventoryLedger.product_id == product_id,
                    InventoryLedger.warehouse_id == warehouse_id,
                    InventoryLedger.batch_no == batch_no,
                )
                .first()
            )
            if not ledger:
                return {"success": False, "message": "库存台账记录不存在"}
            reserved = Decimal(str(ledger.reserved_quantity or 0))
            if reserved < qty:
                return {"success": False, "message": "预留数量不足，无法释放"}
            now = datetime.now()
            if not _order_ledger_cas(
                db, ledger, physical_delta=Decimal("0"),
                available_delta=qty, reserved_delta=-qty, now=now,
            ):
                return {"success": False, "message": "预留已并发变化或账实不一致，无法释放"}
            db.flush()
            txn = InventoryTransaction(
                ledger_id=ledger.id,
                transaction_type="release",
                product_id=product_id,
                warehouse_id=warehouse_id,
                location_id=location_id,
                batch_no=batch_no,
                quantity=Decimal("0"),
                before_quantity=Decimal(str(ledger.quantity or 0)),
                after_quantity=Decimal(str(ledger.quantity or 0)),
                ordered_quantity=Decimal("0"),
                delivered_quantity=Decimal("0"),
                sales_order_id=sales_order_id,
                sales_order_item_id=sales_order_item_id,
                reference_type="sale_release",
                reference_id=sales_order_id,
                transaction_date=now,
                operator=operator,
                remark=remark,
                created_at=now,
            )
            db.add(txn)
            return {
                "success": True,
                "ledger_id": ledger.id,
                "reserved_quantity": float(ledger.reserved_quantity),
                "available_quantity": float(ledger.available_quantity),
            }

        if db is not None:
            return cast("dict[str, Any]", _run(db))
        with get_db() as db:
            try:
                result = _run(db)
                if result["success"]:
                    db.commit()
                return cast("dict[str, Any]", result)
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                logger.error("释放预留失败: %s", e)
                return {"success": False, "message": str(e)}

    def restock_for_order(
        self,
        product_id: int,
        warehouse_id: int,
        quantity: float,
        *,
        sales_order_id: int,
        sales_order_item_id: int,
        batch_no: str | None = None,
        location_id: int | None = None,
        operator: str | None = None,
        remark: str | None = None,
        db: Any = None,
    ) -> dict[str, Any]:
        """按单回补：退货生成反向 move 并把库存加回 available，写一条 return 流水。"""
        qty = _order_quantity(quantity)
        if qty is None:
            return {"success": False, "message": "回补数量必须大于 0"}

        def _run(db):
            ledger = (
                db.query(_facade().InventoryLedger)
                .filter(
                    _facade().InventoryLedger.product_id == product_id,
                    _facade().InventoryLedger.warehouse_id == warehouse_id,
                    _facade().InventoryLedger.batch_no == batch_no,
                    *(
                        (_facade().InventoryLedger.location_id == location_id,)
                        if location_id is not None else ()
                    ),
                )
                .first()
            )
            now = datetime.now()
            if not ledger:
                ledger = _facade().InventoryLedger(
                    product_id=product_id,
                    warehouse_id=warehouse_id,
                    location_id=location_id,
                    batch_no=batch_no,
                    quantity=qty,
                    available_quantity=qty,
                    reserved_quantity=Decimal("0"),
                    unit="个",
                    in_date=now.date(),
                    created_at=now,
                    updated_at=now,
                )
                db.add(ledger)
                db.flush()
                before = Decimal("0")
            else:
                before = Decimal(str(ledger.quantity or 0))
                if not _order_ledger_cas(
                    db, ledger, physical_delta=qty,
                    available_delta=qty, reserved_delta=Decimal("0"), now=now,
                ):
                    return {"success": False, "message": "退货库存已并发变化或账实不一致，未回补"}
                db.flush()
            txn = _facade().InventoryTransaction(
                ledger_id=ledger.id,
                transaction_type="return",
                product_id=product_id,
                warehouse_id=warehouse_id,
                location_id=location_id,
                batch_no=batch_no,
                quantity=qty,
                before_quantity=before,
                after_quantity=Decimal(str(ledger.quantity or 0)),
                ordered_quantity=Decimal("0"),
                delivered_quantity=Decimal("0"),
                sales_order_id=sales_order_id,
                sales_order_item_id=sales_order_item_id,
                reference_type="sale_return",
                reference_id=sales_order_id,
                transaction_date=now,
                operator=operator,
                remark=remark,
                created_at=now,
            )
            db.add(txn)
            return {
                "success": True,
                "ledger_id": ledger.id,
                "quantity": float(ledger.quantity or 0),
                "available_quantity": float(ledger.available_quantity or 0),
            }

        if db is not None:
            return cast("dict[str, Any]", _run(db))
        with _facade().get_db() as db:
            try:
                result = _run(db)
                if result["success"]:
                    db.commit()
                return cast("dict[str, Any]", result)
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                _facade().logger.error("按单回补失败: %s", e)
                return {"success": False, "message": str(e)}
