"""Inventory ledger lookup and summary operations."""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import func

logger = logging.getLogger("app.services.inventory_service")


def _facade():
    return importlib.import_module("app.services.inventory_service")


class InventoryLookupMixin:
    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

    def get_inventory(
        self,
        warehouse_id: int | None = None,
        product_id: int | None = None,
        batch_no: str | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> dict[str, Any]:
        with _facade().get_db() as db:
            query = db.query(_facade().InventoryLedger).join(_facade().Product)
            if warehouse_id:
                query = query.filter(_facade().InventoryLedger.warehouse_id == warehouse_id)
            if product_id:
                query = query.filter(_facade().InventoryLedger.product_id == product_id)
            if batch_no:
                query = query.filter(_facade().InventoryLedger.batch_no == batch_no)
            total = query.count()
            items = (
                query.order_by(_facade().InventoryLedger.created_at.desc())
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
