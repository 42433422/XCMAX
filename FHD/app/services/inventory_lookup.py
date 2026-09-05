"""Inventory ledger lookup and summary operations."""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

logger = logging.getLogger("app.services.inventory_service")
INVENTORY_EXPORT_ROW_LIMIT = 50_000


def _facade():
    return importlib.import_module("app.services.inventory_service")


class InventoryLookupMixin:
    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

    @staticmethod
    def _inventory_query(db, *, warehouse_id=None, product_id=None, batch_no=None, keyword=None):
        """Share filters and the existing tenant-scoped session for list and export."""
        query = db.query(_facade().InventoryLedger).join(_facade().Product)
        if warehouse_id:
            query = query.filter(_facade().InventoryLedger.warehouse_id == warehouse_id)
        if product_id:
            query = query.filter(_facade().InventoryLedger.product_id == product_id)
        if batch_no:
            query = query.filter(_facade().InventoryLedger.batch_no == batch_no)
        search = str(keyword or "").strip()
        if search:
            query = query.filter(
                or_(
                    _facade().Product.name.icontains(search, autoescape=True),
                    _facade().Product.model_number.icontains(search, autoescape=True),
                )
            )
        return query

    def get_inventory(
        self,
        warehouse_id: int | None = None,
        product_id: int | None = None,
        batch_no: str | None = None,
        page: int = 1,
        per_page: int = 50,
        keyword: str | None = None,
    ) -> dict[str, Any]:
        with _facade().get_db() as db:
            query = self._inventory_query(
                db,
                warehouse_id=warehouse_id,
                product_id=product_id,
                batch_no=batch_no,
                keyword=keyword,
            )
            total = query.count()
            items = (
                query.order_by(
                    _facade().InventoryLedger.created_at.desc(), _facade().InventoryLedger.id.desc()
                )
                .offset((page - 1) * per_page)
                .limit(per_page)
                .all()
            )
            result = []
            for item in items:
                item_dict = self._model_to_dict(item)
                item_dict["product_name"] = item.product.name if item.product else None
                item_dict["product_code"] = item.product.model_number if item.product else None
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

    def get_inventory_export(self, **filters: Any) -> dict[str, Any]:
        """Read one bounded SQL snapshot, without count/page or lazy-load races."""
        with _facade().get_db() as db:
            ledger = _facade().InventoryLedger
            items = (
                self._inventory_query(db, **filters)
                .options(joinedload(ledger.product), joinedload(ledger.warehouse))
                .order_by(ledger.created_at.desc(), ledger.id.desc())
                .limit(INVENTORY_EXPORT_ROW_LIMIT + 1)
                .all()
            )
            if len(items) > INVENTORY_EXPORT_ROW_LIMIT:
                return {
                    "success": False,
                    "error_code": "INVENTORY_EXPORT_LIMIT",
                    "message": f"库存导出最多支持 {INVENTORY_EXPORT_ROW_LIMIT:,} 条，请缩小仓库或关键词筛选范围后重试。",
                }
            if not items:
                return {
                    "success": False,
                    "error_code": "INVENTORY_EXPORT_EMPTY",
                    "message": "当前筛选条件下没有库存数据可导出。",
                }
            return {
                "success": True,
                "total": len(items),
                "data": [
                    {
                        "product_name": item.product.name if item.product else "",
                        "product_code": item.product.model_number if item.product else "",
                        "warehouse_name": item.warehouse.name if item.warehouse else "",
                        "batch_no": item.batch_no,
                        "quantity": item.quantity,
                        "available_quantity": item.available_quantity,
                        "unit": item.unit,
                        "in_date": item.in_date,
                    }
                    for item in items
                ],
            }

    def get_inventory_summary(self, warehouse_id: int | None = None) -> dict[str, Any]:
        with _facade().get_db() as db:
            query = db.query(
                _facade().InventoryLedger.product_id,
                _facade().Product.name.label("product_name"),
                _facade().Product.model_number,
                func.sum(_facade().InventoryLedger.quantity).label("total_quantity"),
                func.sum(_facade().InventoryLedger.available_quantity).label("total_available"),
            ).join(_facade().Product)
            if warehouse_id:
                query = query.filter(_facade().InventoryLedger.warehouse_id == warehouse_id)
            query = query.group_by(
                _facade().InventoryLedger.product_id,
                _facade().Product.name,
                _facade().Product.model_number,
            )
            items = query.all()
            return {
                "success": True,
                "data": [
                    {
                        "product_id": item.product_id,
                        "product_name": item.product_name,
                        "model_number": item.model_number,
                        "total_quantity": self._decimal_to_float(item.total_quantity),
                        "total_available": self._decimal_to_float(item.total_available),
                    }
                    for item in items
                ],
            }
