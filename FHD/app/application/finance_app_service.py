"""财务应用服务：出货与采购派生看板，以及手工凭证。"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.db.models.finance import FinancialTransaction
from app.db.models.purchase import PurchaseOrder, Supplier
from app.db.models.shipment import ShipmentRecord
from app.db.session import get_db
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.time import utc_now_naive

logger = logging.getLogger(__name__)


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


_FINAL_FINANCE_STATUSES = frozenset({"posted", "completed", "paid", "settled", "reconciled"})


def _valid_finance_amount(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("财务金额必须是大于零的两位小数")
    try:
        amount = Decimal(str(value))
        if (
            not amount.is_finite() or amount <= 0
            or amount != amount.quantize(Decimal("0.01"))
        ):
            raise ValueError("财务金额必须是大于零的两位小数")
        return amount
    except (TypeError, InvalidOperation) as exc:
        raise ValueError("财务金额必须是大于零的两位小数") from exc


def _same_financial_posting(posted: FinancialTransaction, data: dict[str, Any], amount: Decimal) -> bool:
    return (
        Decimal(str(posted.amount)) == amount
        and posted.currency == data.get("currency", "CNY")
        and (
            "counterparty_id" not in data
            or posted.counterparty_id == data.get("counterparty_id")
        )
        and (
            "counterparty_name" not in data
            or posted.counterparty_name == data.get("counterparty_name")
        )
    )


def _posted_financial_transaction(db, transaction_type, reference_type, reference_id):
    if not reference_type or reference_id in (None, ""):
        return None
    query = db.query(FinancialTransaction).filter(
        FinancialTransaction.transaction_type == transaction_type,
        FinancialTransaction.reference_type == reference_type,
        FinancialTransaction.reference_id == reference_id,
    )
    from app.infrastructure.tenant_scope import current_tenant_id

    tenant_id = current_tenant_id()
    if tenant_id is not None:
        query = query.filter(FinancialTransaction.tenant_id == tenant_id)
    return query.first()


class FinanceAppService:
    """财务应用服务"""

    # ── 财务看板 ─────────────────────────────────────────────────

    def get_dashboard(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> dict[str, Any]:
        """财务总览：收入、成本、应收、应付、毛利。"""
        with get_db() as db:
            # 销售收入（出货单金额汇总）
            shipment_q = db.query(func.sum(ShipmentRecord.amount))
            if start_date:
                shipment_q = shipment_q.filter(ShipmentRecord.created_at >= start_date)
            if end_date:
                shipment_q = shipment_q.filter(ShipmentRecord.created_at <= end_date)
            total_revenue = _to_float(shipment_q.scalar()) or 0.0

            # 采购成本（采购订单实际支付额）
            purchase_q = db.query(func.sum(PurchaseOrder.paid_amount))
            if start_date:
                purchase_q = purchase_q.filter(PurchaseOrder.order_date >= start_date)
            if end_date:
                purchase_q = purchase_q.filter(PurchaseOrder.order_date <= end_date)
            total_cost = _to_float(purchase_q.scalar()) or 0.0

            # 应付款（采购订单中 total_amount - paid_amount，状态非 cancelled）
            ap_q = db.query(
                func.sum(PurchaseOrder.total_amount - PurchaseOrder.paid_amount)
            ).filter(PurchaseOrder.status.notin_(["cancelled", "completed"]))
            total_payable = _to_float(ap_q.scalar()) or 0.0

            # 手工凭证汇总
            manual_receipt = (
                _to_float(
                    db.query(func.sum(FinancialTransaction.amount))
                    .filter(FinancialTransaction.transaction_type == "receipt")
                    .filter(FinancialTransaction.status == "completed")
                    .scalar()
                )
                or 0.0
            )

            manual_payment = (
                _to_float(
                    db.query(func.sum(FinancialTransaction.amount))
                    .filter(FinancialTransaction.transaction_type == "payment")
                    .filter(FinancialTransaction.status == "completed")
                    .scalar()
                )
                or 0.0
            )

            gross_profit = total_revenue - total_cost
            gross_margin = (gross_profit / total_revenue * 100) if total_revenue else 0.0

            return {
                "success": True,
                "data": {
                    "total_revenue": total_revenue,
                    "total_cost": total_cost,
                    "gross_profit": round(gross_profit, 2),
                    "gross_margin_pct": round(gross_margin, 2),
                    "total_payable": round(total_payable, 2),
                    "manual_receipt": manual_receipt,
                    "manual_payment": manual_payment,
                    "period": {
                        "start": start_date.isoformat() if start_date else None,
                        "end": end_date.isoformat() if end_date else None,
                    },
                },
            }

    # ── 应收账款 ─────────────────────────────────────────────────

    def get_receivables(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        status: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """应收账款列表（来自 FinancialTransaction receivable 类型）。"""
        with get_db() as db:
            q = db.query(FinancialTransaction).filter(
                FinancialTransaction.transaction_type.in_(["receivable", "receipt"])
            )
            if start_date:
                q = q.filter(FinancialTransaction.transaction_date >= start_date)
            if end_date:
                q = q.filter(FinancialTransaction.transaction_date <= end_date)
            if status:
                q = q.filter(FinancialTransaction.status == status)

            total = q.count()
            items = (
                q.order_by(FinancialTransaction.transaction_date.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
                .all()
            )
            return {
                "success": True,
                "data": [i.to_dict() for i in items],
                "total": total,
                "page": page,
                "per_page": per_page,
            }

    # ── 应付账款 ─────────────────────────────────────────────────

    def get_payables(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        status: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """应付账款列表（来自采购订单 + FinancialTransaction payable 类型）。"""
        with get_db() as db:
            q = (
                db.query(PurchaseOrder)
                .join(Supplier, PurchaseOrder.supplier_id == Supplier.id, isouter=True)
                .filter(PurchaseOrder.status.notin_(["cancelled"]))
            )

            if start_date:
                q = q.filter(PurchaseOrder.order_date >= start_date)
            if end_date:
                q = q.filter(PurchaseOrder.order_date <= end_date)
            if status:
                q = q.filter(PurchaseOrder.status == status)

            total = q.count()
            orders = (
                q.order_by(PurchaseOrder.order_date.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
                .all()
            )

            data = []
            for o in orders:
                data.append(
                    {
                        "id": o.id,
                        "order_no": o.order_no,
                        "supplier_name": o.supplier.name if o.supplier else None,
                        "total_amount": _to_float(o.total_amount),
                        "paid_amount": _to_float(o.paid_amount),
                        "outstanding": _to_float(o.total_amount - (o.paid_amount or 0)),
                        "status": o.status,
                        "order_date": o.order_date.isoformat() if o.order_date else None,
                        "delivery_date": o.delivery_date.isoformat() if o.delivery_date else None,
                    }
                )

            return {
                "success": True,
                "data": data,
                "total": total,
                "page": page,
                "per_page": per_page,
            }

    # ── 收支流水（手工凭证 CRUD）────────────────────────────────────

    def list_transactions(
        self,
        transaction_type: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        status: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        with get_db() as db:
            q = db.query(FinancialTransaction)
            if transaction_type:
                q = q.filter(FinancialTransaction.transaction_type == transaction_type)
            if start_date:
                q = q.filter(FinancialTransaction.transaction_date >= start_date)
            if end_date:
                q = q.filter(FinancialTransaction.transaction_date <= end_date)
            if status:
                q = q.filter(FinancialTransaction.status == status)

            total = q.count()
            items = (
                q.order_by(FinancialTransaction.transaction_date.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
                .all()
            )
            return {
                "success": True,
                "data": [i.to_dict() for i in items],
                "total": total,
                "page": page,
                "per_page": per_page,
            }

    def get_transaction(self, txn_id: int) -> dict[str, Any]:
        with get_db() as db:
            txn = db.query(FinancialTransaction).filter(FinancialTransaction.id == txn_id).first()
            if not txn:
                return {"success": False, "message": "凭证不存在"}
            return {"success": True, "data": txn.to_dict()}

    def create_transaction(self, data: dict[str, Any]) -> dict[str, Any]:
        try:
            amount = _valid_finance_amount(data["amount"])
        except (KeyError, ValueError) as exc:
            return {"success": False, "message": str(exc)}
        with get_db() as db:
            try:
                reference_type = data.get("reference_type")
                reference_id = data.get("reference_id")
                if isinstance(reference_id, str) and reference_id.isdigit():
                    reference_id = int(reference_id)
                if reference_type and reference_id not in (None, ""):
                    posted = _posted_financial_transaction(
                        db,
                        data["transaction_type"],
                        reference_type,
                        reference_id,
                    )
                    if posted is not None:
                        if not _same_financial_posting(posted, data, amount):
                            return {
                                "success": False,
                                "error_code": "finance_reference_conflict",
                                "message": "该业务单据已有不同金额、币种或交易方的原始流水",
                            }
                        return {
                            "success": True,
                            "message": "该业务单据已登记，未重复入账",
                            "data": posted.to_dict(),
                        }
                txn = FinancialTransaction(
                    transaction_type=data["transaction_type"],
                    amount=amount,
                    currency=data.get("currency", "CNY"),
                    reference_type=reference_type,
                    reference_id=reference_id,
                    description=data.get("description"),
                    transaction_date=_parse_dt(data.get("transaction_date")) or utc_now_naive(),
                    due_date=_parse_dt(data.get("due_date")),
                    status=data.get("status", "pending"),
                    counterparty_name=data.get("counterparty_name"),
                    counterparty_id=data.get("counterparty_id"),
                    created_by=data.get("created_by"),
                )
                db.add(txn)
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    raced = _posted_financial_transaction(
                        db,
                        data["transaction_type"],
                        reference_type,
                        reference_id,
                    )
                    if raced is None:
                        raise
                    if not _same_financial_posting(raced, data, amount):
                        return {
                            "success": False,
                            "error_code": "finance_reference_conflict",
                            "message": "并发写入的原始流水与本请求金额、币种或交易方冲突",
                        }
                    return {
                        "success": True,
                        "message": "该业务单据已登记，未重复入账",
                        "data": raced.to_dict(),
                    }
                db.refresh(txn)
                try:
                    from app.neuro_bus.application_neuro_bridge import (
                        neuro_notify_transaction_changed,
                    )

                    neuro_notify_transaction_changed(
                        "created",
                        transaction_id=txn.id,
                        amount=float(txn.amount or 0),
                        txn_type=txn.transaction_type or "",
                    )
                except RECOVERABLE_ERRORS:
                    logger.debug("neuro_notify_transaction_changed skipped", exc_info=True)
                return {"success": True, "data": txn.to_dict()}
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                logger.error("create_transaction failed: %s", e)
                return {"success": False, "message": str(e)}

    def update_transaction(self, txn_id: int, data: dict[str, Any]) -> dict[str, Any]:
        if data.get("amount") is not None:
            try:
                _valid_finance_amount(data["amount"])
            except ValueError as exc:
                return {"success": False, "message": str(exc)}
        with get_db() as db:
            try:
                txn = (
                    db.query(FinancialTransaction)
                    .filter(FinancialTransaction.id == txn_id)
                    .with_for_update()
                    .first()
                )
                if not txn:
                    return {"success": False, "message": "凭证不存在"}
                if txn.journal_entry_id is not None or txn.status in _FINAL_FINANCE_STATUSES:
                    return {"success": False, "message": "已过账或已关联会计凭证的财务流水不可直接修改，请走冲销"}
                if txn.reference_type and txn.reference_id is not None and any(
                    key in data for key in ("amount", "currency", "reference_type", "reference_id")
                ):
                    return {"success": False, "message": "业务单据绑定的金额、币种及原单据引用不可改写"}
                if data.get("status") in _FINAL_FINANCE_STATUSES:
                    return {"success": False, "message": "财务流水不能直接标记已过账，需原财务记账流程"}

                updatable = {
                    "amount",
                    "currency",
                    "description",
                    "status",
                    "due_date",
                    "transaction_date",
                    "counterparty_name",
                    "counterparty_id",
                    "reference_type",
                    "reference_id",
                }
                for k, v in data.items():
                    if k in updatable and v is not None:
                        if k == "amount":
                            v = _valid_finance_amount(v)
                        elif k in ("transaction_date", "due_date"):
                            v = _parse_dt(v)
                        setattr(txn, k, v)
                txn.updated_at = utc_now_naive()
                db.commit()
                db.refresh(txn)
                try:
                    from app.neuro_bus.application_neuro_bridge import (
                        neuro_notify_transaction_changed,
                    )

                    neuro_notify_transaction_changed(
                        "updated",
                        transaction_id=txn.id,
                        amount=float(txn.amount or 0),
                        txn_type=txn.transaction_type or "",
                    )
                except RECOVERABLE_ERRORS:
                    logger.debug("neuro_notify_transaction_changed skipped", exc_info=True)
                return {"success": True, "data": txn.to_dict()}
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                logger.error("update_transaction failed: %s", e)
                return {"success": False, "message": str(e)}

    def delete_transaction(self, txn_id: int) -> dict[str, Any]:
        with get_db() as db:
            try:
                txn = (
                    db.query(FinancialTransaction)
                    .filter(FinancialTransaction.id == txn_id)
                    .with_for_update()
                    .first()
                )
                if not txn:
                    return {"success": False, "message": "凭证不存在"}
                if (
                    txn.journal_entry_id is not None
                    or txn.status in _FINAL_FINANCE_STATUSES
                    or (txn.reference_type and txn.reference_id is not None)
                ):
                    return {"success": False, "message": "已过账或有关联单据的流水禁止硬删除，请走原会计冲销"}
                _txn_id = txn.id
                _txn_amount = float(txn.amount or 0)
                _txn_type = txn.transaction_type or ""
                db.delete(txn)
                db.commit()
                try:
                    from app.neuro_bus.application_neuro_bridge import (
                        neuro_notify_transaction_changed,
                    )

                    neuro_notify_transaction_changed(
                        "updated",
                        transaction_id=_txn_id,
                        amount=_txn_amount,
                        txn_type=_txn_type,
                    )
                except RECOVERABLE_ERRORS:
                    logger.debug("neuro_notify_transaction_changed skipped", exc_info=True)
                return {"success": True, "message": "凭证已删除"}
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                logger.error("delete_transaction failed: %s", e)
                return {"success": False, "message": str(e)}

    # ── 月度趋势 ────────────────────────────────────────────────

    def get_monthly_trend(self, year: int | None = None) -> dict[str, Any]:
        """按月统计收入/支出趋势（最近12个月）。"""
        import calendar

        target_year = year or utc_now_naive().year
        with get_db() as db:
            months = []
            for m in range(1, 13):
                month_start = datetime(target_year, m, 1)
                last_day = calendar.monthrange(target_year, m)[1]
                month_end = datetime(target_year, m, last_day, 23, 59, 59)

                revenue = (
                    _to_float(
                        db.query(func.sum(ShipmentRecord.amount))
                        .filter(
                            ShipmentRecord.created_at >= month_start,
                            ShipmentRecord.created_at <= month_end,
                        )
                        .scalar()
                    )
                    or 0.0
                )

                cost = (
                    _to_float(
                        db.query(func.sum(PurchaseOrder.paid_amount))
                        .filter(
                            PurchaseOrder.order_date >= month_start,
                            PurchaseOrder.order_date <= month_end,
                        )
                        .scalar()
                    )
                    or 0.0
                )

                months.append(
                    {
                        "month": f"{target_year}-{m:02d}",
                        "revenue": revenue,
                        "cost": cost,
                        "profit": round(revenue - cost, 2),
                    }
                )

            return {"success": True, "data": months, "year": target_year}


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None
