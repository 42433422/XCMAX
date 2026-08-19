# ruff: noqa
"""Order reservation, deduction, and restock operations."""
from __future__ import annotations
import importlib
import logging
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast
from app.utils.operational_errors import RECOVERABLE_ERRORS
logger = logging.getLogger('app.services.inventory_service')

def _facade():
    return importlib.import_module('app.services.inventory_service')

class InventoryOrdersMixin:
    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any:
            ...

    def reserve_for_order(self, product_id: int, warehouse_id: int, quantity: float, *, sales_order_id: int, sales_order_item_id: int, batch_no: str | None=None, location_id: int | None=None, operator: str | None=None, remark: str | None=None, db: Any=None) -> dict[str, Any]:
        """按单预留：将可用库存转入 reserved，并写一条 reserve 流水（stock move）。"""
        qty = Decimal(str(quantity))
        if qty <= 0:
            return {'success': False, 'message': '预留数量必须大于 0'}

        def _run(db):
            ledger = db.query(_facade().InventoryLedger).filter(_facade().InventoryLedger.product_id == product_id, _facade().InventoryLedger.warehouse_id == warehouse_id, _facade().InventoryLedger.batch_no == batch_no).first()
            if not ledger:
                return {'success': False, 'message': '库存台账记录不存在'}
            available = Decimal(str(ledger.available_quantity or 0))
            if available < qty:
                return {'success': False, 'message': '可用库存不足，无法预留'}
            now = datetime.now()
            ledger.reserved_quantity = Decimal(str(ledger.reserved_quantity or 0)) + qty
            ledger.available_quantity = available - qty
            ledger.updated_at = now
            db.flush()
            txn = _facade().InventoryTransaction(ledger_id=ledger.id, transaction_type='reserve', product_id=product_id, warehouse_id=warehouse_id, location_id=location_id, batch_no=batch_no, quantity=Decimal('0'), before_quantity=Decimal(str(ledger.quantity or 0)), after_quantity=Decimal(str(ledger.quantity or 0)), ordered_quantity=qty, delivered_quantity=Decimal('0'), sales_order_id=sales_order_id, sales_order_item_id=sales_order_item_id, reference_type='sale_reserve', reference_id=sales_order_id, transaction_date=now, operator=operator, remark=remark, created_at=now)
            db.add(txn)
            return {'success': True, 'ledger_id': ledger.id, 'reserved_quantity': float(ledger.reserved_quantity), 'available_quantity': float(ledger.available_quantity)}
        if db is not None:
            return cast('dict[str, Any]', _run(db))
        with _facade().get_db() as db:
            try:
                result = _run(db)
                if result['success']:
                    db.commit()
                return cast('dict[str, Any]', result)
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                _facade().logger.error('按单预留失败: %s', e)
                return {'success': False, 'message': str(e)}

    def deduct_for_order(self, product_id: int, warehouse_id: int, quantity: float, *, sales_order_id: int, sales_order_item_id: int, batch_no: str | None=None, location_id: int | None=None, operator: str | None=None, remark: str | None=None, db: Any=None) -> dict[str, Any]:
        """按单扣减：发货时真实扣减库存并消耗对应预留，写一条 out 流水（stock move）。"""
        qty = Decimal(str(quantity))
        if qty <= 0:
            return {'success': False, 'message': '扣减数量必须大于 0'}

        def _run(db):
            ledger = db.query(_facade().InventoryLedger).filter(_facade().InventoryLedger.product_id == product_id, _facade().InventoryLedger.warehouse_id == warehouse_id, _facade().InventoryLedger.batch_no == batch_no).first()
            if not ledger:
                return {'success': False, 'message': '库存台账记录不存在'}
            available = Decimal(str(ledger.available_quantity or 0))
            if available < qty:
                return {'success': False, 'message': '可用库存不足，无法出库'}
            now = datetime.now()
            before = Decimal(str(ledger.quantity or 0))
            ledger.quantity = before - qty
            reserved = Decimal(str(ledger.reserved_quantity or 0))
            ledger.reserved_quantity = max(Decimal('0'), reserved - min(reserved, qty))
            ledger.available_quantity = Decimal(str(ledger.quantity)) - Decimal(str(ledger.reserved_quantity))
            ledger.updated_at = now
            db.flush()
            txn = _facade().InventoryTransaction(ledger_id=ledger.id, transaction_type='out', product_id=product_id, warehouse_id=warehouse_id, location_id=location_id, batch_no=batch_no, quantity=-qty, before_quantity=before, after_quantity=Decimal(str(ledger.quantity)), ordered_quantity=qty, delivered_quantity=qty, sales_order_id=sales_order_id, sales_order_item_id=sales_order_item_id, reference_type='sale_delivery', reference_id=sales_order_id, transaction_date=now, operator=operator, remark=remark, created_at=now)
            db.add(txn)
            return {'success': True, 'ledger_id': ledger.id, 'quantity': float(ledger.quantity), 'available_quantity': float(ledger.available_quantity)}
        if db is not None:
            return cast('dict[str, Any]', _run(db))
        with _facade().get_db() as db:
            try:
                result = _run(db)
                if result['success']:
                    db.commit()
                return cast('dict[str, Any]', result)
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                _facade().logger.error('按单扣减失败: %s', e)
                return {'success': False, 'message': str(e)}

    def restock_for_order(self, product_id: int, warehouse_id: int, quantity: float, *, sales_order_id: int, sales_order_item_id: int, batch_no: str | None=None, location_id: int | None=None, operator: str | None=None, remark: str | None=None, db: Any=None) -> dict[str, Any]:
        """按单回补：退货生成反向 move 并把库存加回 available，写一条 return 流水。"""
        qty = Decimal(str(quantity))
        if qty <= 0:
            return {'success': False, 'message': '回补数量必须大于 0'}

        def _run(db):
            ledger = db.query(_facade().InventoryLedger).filter(_facade().InventoryLedger.product_id == product_id, _facade().InventoryLedger.warehouse_id == warehouse_id, _facade().InventoryLedger.batch_no == batch_no).first()
            now = datetime.now()
            if not ledger:
                ledger = _facade().InventoryLedger(product_id=product_id, warehouse_id=warehouse_id, location_id=location_id, batch_no=batch_no, quantity=qty, available_quantity=qty, reserved_quantity=Decimal('0'), unit='个', in_date=now.date(), created_at=now, updated_at=now)
                db.add(ledger)
                db.flush()
                before = Decimal('0')
            else:
                before = Decimal(str(ledger.quantity or 0))
                ledger.quantity = before + qty
                ledger.available_quantity = Decimal(str(ledger.available_quantity or 0)) + qty
                ledger.updated_at = now
                db.flush()
            txn = _facade().InventoryTransaction(ledger_id=ledger.id, transaction_type='return', product_id=product_id, warehouse_id=warehouse_id, location_id=location_id, batch_no=batch_no, quantity=qty, before_quantity=before, after_quantity=Decimal(str(ledger.quantity or 0)), ordered_quantity=Decimal('0'), delivered_quantity=Decimal('0'), sales_order_id=sales_order_id, sales_order_item_id=sales_order_item_id, reference_type='sale_return', reference_id=sales_order_id, transaction_date=now, operator=operator, remark=remark, created_at=now)
            db.add(txn)
            return {'success': True, 'ledger_id': ledger.id, 'quantity': float(ledger.quantity or 0), 'available_quantity': float(ledger.available_quantity or 0)}
        if db is not None:
            return cast('dict[str, Any]', _run(db))
        with _facade().get_db() as db:
            try:
                result = _run(db)
                if result['success']:
                    db.commit()
                return cast('dict[str, Any]', result)
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                _facade().logger.error('按单回补失败: %s', e)
                return {'success': False, 'message': str(e)}
