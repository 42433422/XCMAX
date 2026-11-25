"""Supplier CRUD and aggregate reads for :mod:`purchase_service`."""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError

from app.db.models import PurchaseOrder, Supplier
from app.infrastructure.tenant_scope import current_tenant_id
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

DATE_FIELDS = frozenset({"order_date", "delivery_date", "inbound_date"})
_SUPPLIER_MUTABLE = frozenset({
    "name", "contact_person", "contact_phone", "contact_email", "address",
    "payment_terms", "credit_limit", "status", "rating", "remark",
})


def _supplier_credit(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value))
        if (
            not amount.is_finite() or amount < 0
            or amount != amount.quantize(Decimal("0.01"))
        ):
            raise ValueError("供应商信用额度必须是非负两位小数")
        return amount
    except (TypeError, ValueError, InvalidOperation) as exc:
        raise ValueError("供应商信用额度必须是非负两位小数") from exc


def _supplier_name_taken(db: Any, tenant_id: int, name: str, exclude_id: int | None = None) -> bool:
    query = db.query(Supplier.id).filter(
        Supplier.tenant_id == tenant_id,
        func.lower(func.trim(Supplier.name)) == name.casefold(),
        Supplier.status != "deleted",
    )
    if exclude_id is not None:
        query = query.filter(Supplier.id != exclude_id)
    return query.first() is not None


def _supplier_name_lock(db: Any, tenant_id: int, name: str) -> None:
    """Serialize same-name supplier writes on both supported DB engines."""
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite" and not db.in_transaction():
        db.execute(text("BEGIN IMMEDIATE"))
    elif dialect == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"supplier:{tenant_id}:{name.casefold()}"},
        )


def as_date(value: Any, default: date | None = None) -> date | None:
    """SQLite 日期列只接受 date 对象：收敛前端 ISO 字符串与空值。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        return default


def items_without_product(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """明细 product_id 为非空外键：缺失时返回业务错误，而不是在 flush 时抛完整性异常。"""
    missing = [str(i) for i, item in enumerate(items, 1) if not (item or {}).get("product_id")]
    if missing:
        return {"success": False, "message": f"第 {'、'.join(missing)} 行明细未选择产品"}
    return None


def page_result(data: list[Any], total: int, page: int, per_page: int) -> dict[str, Any]:
    return {"success": True, "data": data, "total": total, "page": page, "per_page": per_page}


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
            column.name: (
                value.isoformat()
                if isinstance(value, date)
                else PurchaseSupplierMixin._decimal_to_float(value)
            )
            for column in model.__table__.columns
            for value in [getattr(model, column.name)]
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
        name = str(data.get("name") or "").strip()
        tid = current_tenant_id()
        if tid is None:
            return {"success": False, "message": "缺少已授权企业范围"}
        if not name:
            return {"success": False, "message": "供应商名称不能为空"}
        try:
            credit = _supplier_credit(data.get("credit_limit", 0))
        except ValueError as exc:
            return {"success": False, "message": str(exc)}
        code = str(data.get("code") or "").strip() or f"SUP{datetime.now():%Y%m%d%H%M%S%f}"
        with _get_db() as db:
            try:
                _supplier_name_lock(db, tid, name)
                if _supplier_name_taken(db, tid, name):
                    return {"success": False, "message": "当前企业已有同名有效供应商"}
                supplier = Supplier(
                    tenant_id=tid,
                    code=code,
                    name=name,
                    contact_person=data.get("contact_person"),
                    contact_phone=data.get("contact_phone"),
                    contact_email=data.get("contact_email"),
                    address=data.get("address"),
                    payment_terms=data.get("payment_terms", "月结"),
                    credit_limit=credit,
                    status="active",
                    rating=data.get("rating", 3),
                    remark=data.get("remark"),
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                db.add(supplier)
                db.commit()
                db.refresh(supplier)
                return {"success": True, "data": self._model_to_dict(supplier)}
            except IntegrityError:
                db.rollback()
                return {"success": False, "message": f"供应商编码或身份冲突：{code}"}
            except RECOVERABLE_ERRORS as exc:
                db.rollback()
                logger.error("创建供应商失败: %s", exc)
                return {"success": False, "message": str(exc)}

    def update_supplier(self, supplier_id: int, data: dict[str, Any]) -> dict[str, Any]:
        tid = current_tenant_id()
        if tid is None:
            return {"success": False, "message": "缺少已授权企业范围"}
        forbidden = set(data) - _SUPPLIER_MUTABLE
        if forbidden:
            return {"success": False, "message": "供应商主键、编码及企业身份不可通过普通编辑更改"}
        if data.get("status") not in (None, "active", "inactive"):
            return {"success": False, "message": "供应商删除必须经过关联采购与应付检查"}
        if "name" in data and not str(data["name"] or "").strip():
            return {"success": False, "message": "供应商名称不能为空"}
        try:
            credit = (
                _supplier_credit(data["credit_limit"])
                if "credit_limit" in data else None
            )
        except ValueError as exc:
            return {"success": False, "message": str(exc)}
        with _get_db() as db:
            try:
                supplier = db.query(Supplier).filter(
                    Supplier.id == supplier_id, Supplier.tenant_id == tid
                ).with_for_update().first()
                if supplier is None:
                    return {"success": False, "message": "供应商不存在"}
                name = str(data.get("name") or supplier.name).strip()
                _supplier_name_lock(db, tid, name)
                if _supplier_name_taken(db, tid, name, exclude_id=supplier.id):
                    return {"success": False, "message": "当前企业已有同名有效供应商"}
                for key, value in data.items():
                    if key == "name":
                        value = name
                    elif key == "credit_limit":
                        value = credit
                    setattr(supplier, key, value)
                supplier.updated_at = datetime.now()
                db.commit()
                db.refresh(supplier)
                return {"success": True, "data": self._model_to_dict(supplier)}
            except IntegrityError:
                db.rollback()
                return {"success": False, "message": "供应商身份冲突"}
            except RECOVERABLE_ERRORS as exc:
                db.rollback()
                logger.error("更新供应商失败: %s", exc)
                return {"success": False, "message": str(exc)}

    def delete_supplier(self, supplier_id: int) -> dict[str, Any]:
        tid = current_tenant_id()
        if tid is None:
            return {"success": False, "message": "缺少已授权企业范围"}
        with _get_db() as db:
            try:
                supplier = db.query(Supplier).filter(
                    Supplier.id == supplier_id, Supplier.tenant_id == tid
                ).with_for_update().first()
                if supplier is None:
                    return {"success": False, "message": "供应商不存在"}
                if supplier.status == "deleted":
                    return {"success": False, "message": "供应商已经删除"}
                pending = db.query(PurchaseOrder.id).filter(
                    PurchaseOrder.tenant_id == tid,
                    PurchaseOrder.supplier_id == supplier.id,
                    PurchaseOrder.status.notin_(("cancelled", "rejected")),
                    (
                        PurchaseOrder.status.in_(("draft", "approved", "partial"))
                        | (
                            PurchaseOrder.total_amount
                            > func.coalesce(PurchaseOrder.paid_amount, 0)
                        )
                    ),
                ).first()
                if pending is not None:
                    return {
                        "success": False,
                        "message": "供应商仍有关联未完成采购或未结应付款，禁止删除",
                    }
                supplier.status = "deleted"
                supplier.updated_at = datetime.now()
                db.commit()
                return {"success": True, "message": "供应商已停用，历史关联保留"}
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
