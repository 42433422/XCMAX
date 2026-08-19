# ruff: noqa
"""Inventory count, transaction query, and alert operations."""
from __future__ import annotations
import importlib
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any
from app.utils.operational_errors import RECOVERABLE_ERRORS
logger = logging.getLogger('app.services.inventory_service')

def _facade():
    return importlib.import_module('app.services.inventory_service')

class InventoryCountingMixin:
    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any:
            ...

    def inventory_count(self, product_id: int, warehouse_id: int, actual_quantity: float, batch_no: str | None=None, location_id: int | None=None, operator: str | None=None, remark: str | None=None, confirmed: bool=False) -> dict[str, Any]:
        """盘点功能。

        查询当前台账账面数量，计算差异 diff = actual_quantity - book_quantity。
        - confirmed=False：仅返回差异供对话层反问确认，不实际改动库存。
        - confirmed=True：按实际数量调整台账并写入一条 transaction_type="count" 流水。
        """
        with _facade().get_db() as db:
            try:
                ledger = db.query(_facade().InventoryLedger).filter(_facade().InventoryLedger.product_id == product_id, _facade().InventoryLedger.warehouse_id == warehouse_id, _facade().InventoryLedger.batch_no == batch_no).first()
                if not ledger:
                    return {'success': False, 'message': '库存台账记录不存在，请先入库'}
                book_quantity = float(ledger.quantity or 0)
                actual_quantity = float(actual_quantity)
                diff = actual_quantity - book_quantity
                if not confirmed:
                    return {'success': True, 'confirmed': False, 'message': '盘点待确认', 'data': {'product_id': product_id, 'warehouse_id': warehouse_id, 'batch_no': batch_no, 'book_quantity': book_quantity, 'actual_quantity': actual_quantity, 'diff': diff}}
                now = datetime.now()
                before_quantity = book_quantity
                ledger.quantity = actual_quantity
                ledger.available_quantity = float(ledger.available_quantity or 0) + diff
                if location_id:
                    ledger.location_id = location_id
                ledger.updated_at = now
                db.flush()
                transaction = _facade().InventoryTransaction(ledger_id=ledger.id, transaction_type='count', product_id=product_id, warehouse_id=warehouse_id, location_id=location_id, batch_no=batch_no, quantity=diff, before_quantity=before_quantity, after_quantity=actual_quantity, reference_type='inventory_count', transaction_date=now, operator=operator, remark=remark, created_at=now)
                db.add(transaction)
                db.commit()
                return {'success': True, 'confirmed': True, 'message': '盘点确认成功', 'data': {'product_id': product_id, 'warehouse_id': warehouse_id, 'batch_no': batch_no, 'book_quantity': before_quantity, 'actual_quantity': actual_quantity, 'diff': diff, 'total_quantity': float(ledger.quantity)}}
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                _facade().logger.error('盘点失败: %s', e)
                return {'success': False, 'message': str(e)}

    def get_inventory_transactions(self, product_id: int | None=None, warehouse_id: int | None=None, transaction_type: str | None=None, start_date: datetime | None=None, end_date: datetime | None=None, page: int=1, per_page: int=50) -> dict[str, Any]:
        with _facade().get_db() as db:
            query = db.query(_facade().InventoryTransaction)
            if product_id:
                query = query.filter(_facade().InventoryTransaction.product_id == product_id)
            if warehouse_id:
                query = query.filter(_facade().InventoryTransaction.warehouse_id == warehouse_id)
            if transaction_type:
                query = query.filter(_facade().InventoryTransaction.transaction_type == transaction_type)
            if start_date:
                query = query.filter(_facade().InventoryTransaction.transaction_date >= start_date)
            if end_date:
                query = query.filter(_facade().InventoryTransaction.transaction_date <= end_date)
            total = query.count()
            items = query.order_by(_facade().InventoryTransaction.transaction_date.desc()).offset((page - 1) * per_page).limit(per_page).all()
            result = []
            for item in items:
                item_dict = self._model_to_dict(item)
                item_dict['product_name'] = item.product.name if item.product else None
                item_dict['warehouse_name'] = item.warehouse.name if item.warehouse else None
                item_dict['location_name'] = item.location.name if item.location else None
                result.append(item_dict)
            return {'success': True, 'data': result, 'total': total, 'page': page, 'per_page': per_page}

    def query_transactions(self, **kwargs: Any) -> dict[str, Any]:
        """流水查询薄封装，动作名与 get_inventory_transactions 保持一致。"""
        return self.get_inventory_transactions(**kwargs)

    def get_inventory_alert(self) -> dict[str, Any]:
        with _facade().get_db() as db:
            query = db.query(_facade().InventoryLedger).join(_facade().Product).filter(_facade().InventoryLedger.available_quantity <= 0)
            items = query.all()
            result = []
            for item in items:
                item_dict = self._model_to_dict(item)
                item_dict['product_name'] = item.product.name if item.product else None
                item_dict['product_code'] = item.product.model_number if item.product else None
                result.append(item_dict)
            return {'success': True, 'data': result, 'count': len(result)}
