"""SQLAlchemy purchase repository — supplier and order read paths."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func

from app.application.ports.purchase_repository import PurchaseRepository
from app.db.models import PurchaseOrder, Supplier


class SQLAlchemyPurchaseRepository(PurchaseRepository):
    def get_suppliers(
        self, db: Any, *, status: str | None = None, keyword: str | None = None
    ) -> list[Any]:
        query = db.query(Supplier)
        if status:
            query = query.filter(Supplier.status == status)
        if keyword:
            query = query.filter(
                Supplier.name.like(f"%{keyword}%")
                | Supplier.code.like(f"%{keyword}%")
                | Supplier.contact_person.like(f"%{keyword}%")
            )
        return query.order_by(Supplier.code).all()

    def get_supplier(self, db: Any, supplier_id: int) -> Any | None:
        return db.query(Supplier).filter(Supplier.id == supplier_id).first()

    def get_purchase_orders(
        self,
        db: Any,
        *,
        supplier_id: int | None = None,
        status: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[Any], int]:
        query = db.query(PurchaseOrder).join(Supplier)
        if supplier_id:
            query = query.filter(PurchaseOrder.supplier_id == supplier_id)
        if status:
            query = query.filter(PurchaseOrder.status == status)
        if start_date:
            query = query.filter(PurchaseOrder.order_date >= start_date)
        if end_date:
            query = query.filter(PurchaseOrder.order_date <= end_date)
        total = query.count()
        orders = (
            query.order_by(PurchaseOrder.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        return orders, total

    def supplier_status_summary(self, db: Any) -> dict[str, int]:
        stats = (
            db.query(Supplier.status, func.count(Supplier.id).label("count"))
            .group_by(Supplier.status)
            .all()
        )
        return {status or "unknown": count for status, count in stats}
