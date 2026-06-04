"""SQLAlchemy inventory repository — warehouse and ledger read paths."""

from __future__ import annotations

from typing import Any

from app.application.ports.inventory_repository import InventoryRepository
from app.db.models import InventoryLedger, Product, Warehouse


class SQLAlchemyInventoryRepository(InventoryRepository):
    def get_warehouses(self, db: Any, *, status: str | None = None) -> list[Any]:
        query = db.query(Warehouse)
        if status:
            query = query.filter(Warehouse.status == status)
        return list(query.order_by(Warehouse.code).all())

    def get_warehouse(self, db: Any, warehouse_id: int) -> Any | None:
        return db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()

    def get_inventory_ledger(
        self,
        db: Any,
        *,
        warehouse_id: int | None = None,
        product_id: int | None = None,
        batch_no: str | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[Any], int]:
        query = db.query(InventoryLedger).join(Product)
        if warehouse_id:
            query = query.filter(InventoryLedger.warehouse_id == warehouse_id)
        if product_id:
            query = query.filter(InventoryLedger.product_id == product_id)
        if batch_no:
            query = query.filter(InventoryLedger.batch_no == batch_no)
        total = query.count()
        rows = (
            query.order_by(InventoryLedger.updated_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        return list(rows), total
