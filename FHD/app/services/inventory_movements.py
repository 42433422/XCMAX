"""Inventory in, out, and transfer operations."""

from __future__ import annotations

import importlib
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger("app.services.inventory_service")


def _facade():
    return importlib.import_module("app.services.inventory_service")


class InventoryMovementsMixin:
    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

    def inventory_in(
        self,
        product_id: int,
        warehouse_id: int,
        quantity: float,
        batch_no: str | None = None,
        location_id: int | None = None,
        unit_price: float | None = None,
        reference_type: str | None = None,
        reference_id: int | None = None,
        operator: str | None = None,
        remark: str | None = None,
    ) -> dict[str, Any]:
        with _facade().get_db() as db:
            try:
                product = (
                    db.query(_facade().Product).filter(_facade().Product.id == product_id).first()
                )
                if not product:
                    return {"success": False, "message": "产品不存在"}
                ledger = (
                    db.query(_facade().InventoryLedger)
                    .filter(
                        _facade().InventoryLedger.product_id == product_id,
                        _facade().InventoryLedger.warehouse_id == warehouse_id,
                        _facade().InventoryLedger.batch_no == batch_no,
                    )
                    .first()
                )
                now = datetime.now()
                if ledger:
                    ledger.quantity = float(ledger.quantity or 0) + quantity
                    ledger.available_quantity = float(ledger.available_quantity or 0) + quantity
                    ledger.updated_at = now
                else:
                    ledger = _facade().InventoryLedger(
                        product_id=product_id,
                        warehouse_id=warehouse_id,
                        location_id=location_id,
                        batch_no=batch_no,
                        quantity=quantity,
                        available_quantity=quantity,
                        reserved_quantity=0,
                        unit=product.unit or "个",
                        in_date=now.date(),
                        created_at=now,
                        updated_at=now,
                    )
                    db.add(ledger)
                db.flush()
                transaction = _facade().InventoryTransaction(
                    ledger_id=ledger.id,
                    transaction_type="in",
                    product_id=product_id,
                    warehouse_id=warehouse_id,
                    location_id=location_id,
                    batch_no=batch_no,
                    quantity=quantity,
                    before_quantity=float(ledger.quantity) - quantity,
                    after_quantity=float(ledger.quantity),
                    unit_price=unit_price,
                    total_amount=quantity * unit_price if unit_price else None,
                    reference_type=reference_type,
                    reference_id=reference_id,
                    transaction_date=now,
                    operator=operator,
                    remark=remark,
                    created_at=now,
                )
                db.add(transaction)
                db.commit()
                return {
                    "success": True,
                    "message": "入库成功",
                    "data": {
                        "ledger_id": ledger.id,
                        "quantity": quantity,
                        "total_quantity": float(ledger.quantity),
                    },
                }
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                _facade().logger.error("入库失败: %s", e)
                return {"success": False, "message": str(e)}

    def inventory_out(
        self,
        product_id: int,
        warehouse_id: int,
        quantity: float,
        batch_no: str | None = None,
        location_id: int | None = None,
        reference_type: str | None = None,
        reference_id: int | None = None,
        operator: str | None = None,
        remark: str | None = None,
    ) -> dict[str, Any]:
        with _facade().get_db() as db:
            try:
                query = db.query(_facade().InventoryLedger).filter(
                    _facade().InventoryLedger.product_id == product_id,
                    _facade().InventoryLedger.warehouse_id == warehouse_id,
                    _facade().InventoryLedger.available_quantity >= quantity,
                )
                if batch_no:
                    query = query.filter(_facade().InventoryLedger.batch_no == batch_no)
                if location_id:
                    query = query.filter(_facade().InventoryLedger.location_id == location_id)
                ledger = query.first()
                if not ledger:
                    return {"success": False, "message": "库存不足或库存记录不存在"}
                now = datetime.now()
                ledger.quantity = float(ledger.quantity) - quantity
                ledger.available_quantity = float(ledger.available_quantity) - quantity
                ledger.updated_at = now
                transaction = _facade().InventoryTransaction(
                    ledger_id=ledger.id,
                    transaction_type="out",
                    product_id=product_id,
                    warehouse_id=warehouse_id,
                    location_id=location_id,
                    batch_no=batch_no,
                    quantity=-quantity,
                    before_quantity=float(ledger.quantity) + quantity,
                    after_quantity=float(ledger.quantity),
                    reference_type=reference_type,
                    reference_id=reference_id,
                    transaction_date=now,
                    operator=operator,
                    remark=remark,
                    created_at=now,
                )
                db.add(transaction)
                db.commit()
                return {
                    "success": True,
                    "message": "出库成功",
                    "data": {
                        "ledger_id": ledger.id,
                        "quantity": quantity,
                        "remaining_quantity": float(ledger.quantity),
                    },
                }
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                _facade().logger.error("出库失败: %s", e)
                return {"success": False, "message": str(e)}

    def inventory_transfer(
        self,
        product_id: int,
        from_warehouse_id: int,
        to_warehouse_id: int,
        quantity: float,
        from_location_id: int | None = None,
        to_location_id: int | None = None,
        batch_no: str | None = None,
        operator: str | None = None,
        remark: str | None = None,
    ) -> dict[str, Any]:
        with _facade().get_db() as db:
            try:
                from_ledger = (
                    db.query(_facade().InventoryLedger)
                    .filter(
                        _facade().InventoryLedger.product_id == product_id,
                        _facade().InventoryLedger.warehouse_id == from_warehouse_id,
                        _facade().InventoryLedger.available_quantity >= quantity,
                    )
                    .first()
                )
                if not from_ledger:
                    return {"success": False, "message": "源仓库库存不足"}
                now = datetime.now()
                from_ledger.quantity = float(from_ledger.quantity) - quantity
                from_ledger.available_quantity = float(from_ledger.available_quantity) - quantity
                from_ledger.updated_at = now
                out_transaction = _facade().InventoryTransaction(
                    ledger_id=from_ledger.id,
                    transaction_type="transfer_out",
                    product_id=product_id,
                    warehouse_id=from_warehouse_id,
                    location_id=from_location_id,
                    batch_no=batch_no,
                    quantity=-quantity,
                    before_quantity=float(from_ledger.quantity) + quantity,
                    after_quantity=float(from_ledger.quantity),
                    reference_type="transfer",
                    transaction_date=now,
                    operator=operator,
                    remark=f"调出至仓库{to_warehouse_id}",
                    created_at=now,
                )
                db.add(out_transaction)
                to_ledger = (
                    db.query(_facade().InventoryLedger)
                    .filter(
                        _facade().InventoryLedger.product_id == product_id,
                        _facade().InventoryLedger.warehouse_id == to_warehouse_id,
                        (_facade().InventoryLedger.batch_no == batch_no)
                        | _facade().InventoryLedger.batch_no.is_(None),
                    )
                    .first()
                )
                if to_ledger:
                    to_ledger.quantity = float(to_ledger.quantity) + quantity
                    to_ledger.available_quantity = float(to_ledger.available_quantity) + quantity
                    to_ledger.updated_at = now
                else:
                    to_ledger = _facade().InventoryLedger(
                        product_id=product_id,
                        warehouse_id=to_warehouse_id,
                        location_id=to_location_id,
                        batch_no=batch_no,
                        quantity=quantity,
                        available_quantity=quantity,
                        reserved_quantity=0,
                        unit=from_ledger.unit,
                        in_date=now.date(),
                        created_at=now,
                        updated_at=now,
                    )
                    db.add(to_ledger)
                db.flush()
                in_transaction = _facade().InventoryTransaction(
                    ledger_id=to_ledger.id,
                    transaction_type="transfer_in",
                    product_id=product_id,
                    warehouse_id=to_warehouse_id,
                    location_id=to_location_id,
                    batch_no=batch_no,
                    quantity=quantity,
                    before_quantity=float(to_ledger.quantity) - quantity,
                    after_quantity=float(to_ledger.quantity),
                    reference_type="transfer",
                    transaction_date=now,
                    operator=operator,
                    remark=f"从仓库{from_warehouse_id}调入",
                    created_at=now,
                )
                db.add(in_transaction)
                db.commit()
                return {
                    "success": True,
                    "message": "调拨成功",
                    "data": {
                        "from_ledger_id": from_ledger.id,
                        "to_ledger_id": to_ledger.id,
                        "quantity": quantity,
                    },
                }
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                _facade().logger.error("调拨失败: %s", e)
                return {"success": False, "message": str(e)}
