from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import IntegerPrimaryKeyMixin, TenantScopedMixin, TimestampMixin

# 应收（receivables）分配状态（Odoo account.payment 分配吸收）
RECEIVABLE_STATUS_UNPAID = "unpaid"
RECEIVABLE_STATUS_PARTIAL = "partial"
RECEIVABLE_STATUS_PAID = "paid"
RECEIVABLE_STATUS_REFUNDED = "refunded"
RECEIVABLE_STATUS_VALUES = {
    RECEIVABLE_STATUS_UNPAID,
    RECEIVABLE_STATUS_PARTIAL,
    RECEIVABLE_STATUS_PAID,
    RECEIVABLE_STATUS_REFUNDED,
}


class ReceivableAllocation(IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """应收款分配（Odoo account.payment 吸收）。

    跟踪销售订单的收款在其应收（receivables）上的分配：
    unpaid / partial / paid / refunded。累计收款不超应收，超收被拒；
    同单同金额重复收款幂等；全额 → paid；refund/reversal 更新分配。
    """

    __tablename__ = "receivable_allocations"

    __table_args__ = (
        CheckConstraint(
            "status IN ('unpaid', 'partial', 'paid', 'refunded')",
            name="ck_receivable_allocations_status_valid",
        ),
        CheckConstraint(
            "COALESCE(amount, 0) >= 0",
            name="ck_receivable_allocations_amount_non_negative",
        ),
        CheckConstraint(
            "COALESCE(allocated_amount, 0) >= 0",
            name="ck_receivable_allocations_allocated_amount_non_negative",
        ),
        CheckConstraint(
            "COALESCE(allocated_amount, 0) <= COALESCE(amount, 0)",
            name="ck_receivable_allocations_allocated_le_amount",
        ),
    )

    sales_order_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_orders.id"), nullable=True, index=True
    )
    # 产生分配的记账凭证（收款凭证 journal_entry）
    journal_entry_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("journal_entries.id"), nullable=True, index=True
    )
    # 应收（receivable）分录行（journal_entry_line）
    line_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("journal_entry_lines.id"), nullable=True, index=True
    )
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), default=0)
    allocated_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), default=0)
    status: Mapped[str] = mapped_column(String(20), default="unpaid", index=True)
    reference_type: Mapped[Optional[str]] = mapped_column(String(64))
    reference_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    # 反向/冲销：被冲销的原始分配（refund/reversal 指向）
    reversed_of_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("receivable_allocations.id", name="fk_receivable_allocations_reversed_of_id"),
        nullable=True,
        index=True,
    )
    allocated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    sales_order: Mapped[Optional[object]] = relationship("SalesOrder")
    journal_entry: Mapped[Optional[object]] = relationship("JournalEntry")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sales_order_id": self.sales_order_id,
            "journal_entry_id": self.journal_entry_id,
            "line_id": self.line_id,
            "amount": float(self.amount) if self.amount is not None else 0.0,
            "allocated_amount": (
                float(self.allocated_amount) if self.allocated_amount is not None else 0.0
            ),
            "status": self.status,
            "reference_type": self.reference_type,
            "reference_id": self.reference_id,
            "reversed_of_id": self.reversed_of_id,
            "allocated_at": self.allocated_at.isoformat() if self.allocated_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
