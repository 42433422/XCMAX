"""Inventory count, transaction query, and alert operations."""

from __future__ import annotations

import importlib
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.application.agent_orchestrator.business_write_guard import worker_write_guard
from typing import TYPE_CHECKING, Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger("app.domain.shared_services.inventory_service")


def _facade():
    return importlib.import_module("app.domain.shared_services.inventory_service")


class InventoryCountingMixin:
    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

    def inventory_count(
        self,
        product_id: int,
        warehouse_id: int,
        actual_quantity: float,
        batch_no: str | None = None,
        location_id: int | None = None,
        operator: str | None = None,
        remark: str | None = None,
        confirmed: bool = False,
        expected_book_quantity: str | None = None,
    ) -> dict[str, Any]:
        """Preview or CAS-confirm an inventory count without consuming reservations."""
        try:
            actual = Decimal(str(actual_quantity))
            if (
                not actual.is_finite() or actual < 0
                or actual != actual.quantize(Decimal("0.0001"))
            ):
                raise ValueError("盘点数量必须为四位小数以内的非负数")
        except (ValueError, TypeError, InvalidOperation):
            return {"success": False, "message": "盘点数量必须为四位小数以内的非负数"}
        with _facade().get_db() as db, worker_write_guard(db):
            try:
                model = _facade().InventoryLedger
                ledger = db.query(model).filter(
                    model.product_id == product_id,
                    model.warehouse_id == warehouse_id,
                    model.batch_no == batch_no,
                ).first()
                if ledger is None:
                    return {"success": False, "message": "库存台账记录不存在，请先入库"}
                book = Decimal(str(ledger.quantity or 0))
                available = Decimal(str(ledger.available_quantity or 0))
                reserved = Decimal(str(ledger.reserved_quantity or 0))
                if min(book, available, reserved) < 0 or book != available + reserved:
                    return {
                        "success": False,
                        "error_code": "inventory_ledger_inconsistent",
                        "message": "原库存台账不平衡，禁止盘点覆盖，需先独立对账",
                    }
                if actual < reserved:
                    return {
                        "success": False,
                        "error_code": "inventory_reservation_conflict",
                        "message": "盘点实存量低于已冻结库存，请先核实或释放原预留",
                    }
                if expected_book_quantity is not None:
                    try:
                        expected = Decimal(str(expected_book_quantity))
                    except (TypeError, ValueError, InvalidOperation):
                        return {"success": False, "message": "盘点快照数量无效"}
                    if not expected.is_finite() or expected != book:
                        return {
                            "success": False,
                            "error_code": "inventory_count_stale",
                            "message": "盘点预览后账面数量已变更，请重新盘点",
                        }
                diff = actual - book
                if not confirmed:
                    return {
                        "success": True,
                        "confirmed": False,
                        "message": "盘点待确认",
                        "data": {
                            "product_id": product_id,
                            "warehouse_id": warehouse_id,
                            "batch_no": batch_no,
                            "book_quantity": float(book),
                            "actual_quantity": float(actual),
                            "diff": float(diff),
                        },
                    }
                if location_id is not None:
                    location = db.query(_facade().StorageLocation).filter(
                        _facade().StorageLocation.id == location_id,
                        _facade().StorageLocation.warehouse_id == warehouse_id,
                        _facade().StorageLocation.status == "active",
                    ).first()
                    if location is None:
                        return {"success": False, "message": "盘点库位不属于当前仓库或未启用"}
                now = datetime.now()
                values = {
                    model.quantity: actual,
                    model.available_quantity: actual - reserved,
                    model.updated_at: now,
                }
                if location_id is not None:
                    values[model.location_id] = location_id
                changed = db.query(model).filter(
                    model.id == ledger.id,
                    model.tenant_id == ledger.tenant_id,
                    model.quantity == book,
                    model.available_quantity == available,
                    model.reserved_quantity == reserved,
                ).update(values, synchronize_session=False)
                if changed != 1:
                    db.rollback()
                    return {
                        "success": False,
                        "error_code": "inventory_count_stale",
                        "message": "盘点确认时库存已并发变化，未覆盖新库存",
                    }
                db.refresh(ledger)
                db.add(_facade().InventoryTransaction(
                    ledger_id=ledger.id,
                    transaction_type="count",
                    product_id=product_id,
                    warehouse_id=warehouse_id,
                    location_id=location_id or ledger.location_id,
                    batch_no=batch_no,
                    quantity=diff,
                    before_quantity=book,
                    after_quantity=actual,
                    reference_type="inventory_count",
                    transaction_date=now,
                    operator=operator,
                    remark=remark,
                    created_at=now,
                ))
                db.commit()
                return {
                    "success": True,
                    "confirmed": True,
                    "message": "盘点确认成功",
                    "data": {
                        "product_id": product_id,
                        "warehouse_id": warehouse_id,
                        "batch_no": batch_no,
                        "book_quantity": float(book),
                        "actual_quantity": float(actual),
                        "diff": float(diff),
                        "total_quantity": float(ledger.quantity),
                    },
                }
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                _facade().logger.error("盘点失败: %s", e)
                return {"success": False, "message": str(e)}

    def get_inventory_transactions(
        self,
        product_id: int | None = None,
        warehouse_id: int | None = None,
        transaction_type: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> dict[str, Any]:
        with _facade().get_db() as db:
            query = db.query(_facade().InventoryTransaction)
            if product_id:
                query = query.filter(_facade().InventoryTransaction.product_id == product_id)
            if warehouse_id:
                query = query.filter(_facade().InventoryTransaction.warehouse_id == warehouse_id)
            if transaction_type:
                query = query.filter(
                    _facade().InventoryTransaction.transaction_type == transaction_type
                )
            if start_date:
                query = query.filter(_facade().InventoryTransaction.transaction_date >= start_date)
            if end_date:
                query = query.filter(_facade().InventoryTransaction.transaction_date <= end_date)
            total = query.count()
            items = (
                query.order_by(_facade().InventoryTransaction.transaction_date.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
                .all()
            )
            result = []
            for item in items:
                item_dict = self._model_to_dict(item)
                item_dict["product_name"] = item.product.name if item.product else None
                item_dict["warehouse_name"] = item.warehouse.name if item.warehouse else None
                item_dict["location_name"] = item.location.name if item.location else None
                result.append(item_dict)
            return {
                "success": True,
                "data": result,
                "total": total,
                "page": page,
                "per_page": per_page,
            }

    def query_transactions(self, **kwargs: Any) -> dict[str, Any]:
        """流水查询薄封装，动作名与 get_inventory_transactions 保持一致。"""
        return self.get_inventory_transactions(**kwargs)

    def get_inventory_alert(self) -> dict[str, Any]:
        with _facade().get_db() as db:
            query = (
                db.query(_facade().InventoryLedger)
                .join(_facade().Product)
                .filter(_facade().InventoryLedger.available_quantity <= 0)
            )
            items = query.all()
            result = []
            for item in items:
                item_dict = self._model_to_dict(item)
                item_dict["product_name"] = item.product.name if item.product else None
                item_dict["product_code"] = item.product.model_number if item.product else None
                result.append(item_dict)
            return {"success": True, "data": result, "count": len(result)}
