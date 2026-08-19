"""Supplier CRUD and aggregate reads for :mod:`purchase_service`."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func

from app.db.models import PurchaseOrder, Supplier
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _get_db():
    """Resolve through the compatibility module so existing dependency patches apply."""
    from app.services import purchase_service

    return purchase_service.get_db()


class PurchaseSupplierMixin:
    @staticmethod
    def _decimal_to_float(value: Any) -> Any:
        return float(value) if isinstance(value, Decimal) else value

    @staticmethod
    def _model_to_dict(model: Any) -> dict[str, Any]:
        if model is None:
            return {}
        return {
            column.name: PurchaseSupplierMixin._decimal_to_float(getattr(model, column.name))
            for column in model.__table__.columns
        }

    def get_suppliers(
        self, status: str | None = None, keyword: str | None = None
    ) -> dict[str, Any]:
        with _get_db() as db:
            query = db.query(Supplier)
            if status:
                query = query.filter(Supplier.status == status)
            if keyword:
                query = query.filter(
                    Supplier.name.like(f"%{keyword}%")
                    | Supplier.code.like(f"%{keyword}%")
                    | Supplier.contact_person.like(f"%{keyword}%")
                )
            suppliers = query.order_by(Supplier.code).all()
            return {
                "success": True,
                "data": [self._model_to_dict(supplier) for supplier in suppliers],
                "count": len(suppliers),
            }

    def get_supplier(self, supplier_id: int) -> dict[str, Any]:
        with _get_db() as db:
            supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
            if not supplier:
                return {"success": False, "message": "供应商不存在"}
            return {"success": True, "data": self._model_to_dict(supplier)}

    def create_supplier(self, data: dict[str, Any]) -> dict[str, Any]:
        with _get_db() as db:
            try:
                supplier = Supplier(
                    code=data.get("code"),
                    name=data.get("name"),
                    contact_person=data.get("contact_person"),
                    contact_phone=data.get("contact_phone"),
                    contact_email=data.get("contact_email"),
                    address=data.get("address"),
                    payment_terms=data.get("payment_terms", "月结"),
                    credit_limit=self._decimal_to_float(data.get("credit_limit", 0)),
                    status=data.get("status", "active"),
                    rating=data.get("rating", 3),
                    remark=data.get("remark"),
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                db.add(supplier)
                db.commit()
                db.refresh(supplier)
                return {"success": True, "data": self._model_to_dict(supplier)}
            except RECOVERABLE_ERRORS as exc:
                db.rollback()
                logger.error("创建供应商失败: %s", exc)
                return {"success": False, "message": str(exc)}

    def update_supplier(self, supplier_id: int, data: dict[str, Any]) -> dict[str, Any]:
        with _get_db() as db:
            try:
                supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
                if not supplier:
                    return {"success": False, "message": "供应商不存在"}
                for key, value in data.items():
                    if hasattr(supplier, key):
                        setattr(supplier, key, value)
                supplier.updated_at = datetime.now()
                db.commit()
                db.refresh(supplier)
                return {"success": True, "data": self._model_to_dict(supplier)}
            except RECOVERABLE_ERRORS as exc:
                db.rollback()
                logger.error("更新供应商失败: %s", exc)
                return {"success": False, "message": str(exc)}

    def delete_supplier(self, supplier_id: int) -> dict[str, Any]:
        with _get_db() as db:
            try:
                supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
                if not supplier:
                    return {"success": False, "message": "供应商不存在"}
                supplier.status = "deleted"
                db.commit()
                return {"success": True, "message": "供应商已删除"}
            except RECOVERABLE_ERRORS as exc:
                db.rollback()
                logger.error("删除供应商失败: %s", exc)
                return {"success": False, "message": str(exc)}

    def _generate_order_no(self) -> str:
        return f"PO{datetime.now().strftime('%Y%m%d%H%M%S')}"

    def _generate_inbound_no(self) -> str:
        return f"PI{datetime.now().strftime('%Y%m%d%H%M%S')}"

    def get_supplier_summary(self) -> dict[str, Any]:
        with _get_db() as db:
            stats = (
                db.query(Supplier.status, func.count(Supplier.id).label("count"))
                .group_by(Supplier.status)
                .all()
            )
            result = {status or "unknown": count for status, count in stats}
            return {"success": True, "data": result}

    def get_purchase_summary(
        self, start_date: datetime | None = None, end_date: datetime | None = None
    ) -> dict[str, Any]:
        with _get_db() as db:
            query = db.query(
                PurchaseOrder.status,
                func.count(PurchaseOrder.id).label("count"),
                func.sum(PurchaseOrder.total_amount).label("amount"),
            )
            if start_date:
                query = query.filter(PurchaseOrder.order_date >= start_date)
            if end_date:
                query = query.filter(PurchaseOrder.order_date <= end_date)
            stats = query.group_by(PurchaseOrder.status).all()
            result = {
                status or "unknown": {
                    "count": count,
                    "amount": self._decimal_to_float(amount),
                }
                for status, count, amount in stats
            }
            return {"success": True, "data": result}
