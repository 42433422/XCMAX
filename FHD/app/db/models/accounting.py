from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import IntegerPrimaryKeyMixin, TenantScopedMixin, TimestampMixin

# 会计科目类型（Odoo account.account 吸收）
ACCOUNT_TYPES = {"asset", "liability", "equity", "revenue", "expense"}


class ChartOfAccount(IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """会计科目表（Odoo account.account 吸收：code/name/type/debit_credit）。"""

    __tablename__ = "chart_of_accounts"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(20), default="asset", index=True)
    # 正常余额方向：debit(借) / credit(贷)
    debit_credit: Mapped[str] = mapped_column(String(10), default="debit")
    is_active: Mapped[int] = mapped_column(Integer, default=1)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "type": self.type,
            "debit_credit": self.debit_credit,
            "is_active": self.is_active,
        }


class JournalEntry(IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """记账凭证（Odoo account.move 吸收：一组借贷平衡的 move.line）。"""

    __tablename__ = "journal_entries"

    entry_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    journal_date: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    reference_type: Mapped[Optional[str]] = mapped_column(String(64))
    reference_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    debit_total: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), default=0)
    credit_total: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), default=0)
    # 反向/冲销：被冲销的原始凭证为 reversed_of（冲销凭证记录），原凭证用 reversed_at 时间戳标记已冲销
    reversed_of_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    reversed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    lines: Mapped[list[JournalEntryLine]] = relationship(
        "JournalEntryLine", back_populates="entry", cascade="all, delete-orphan", lazy="selectin"
    )

    def is_balanced(self) -> bool:
        """借贷平衡校验：借方总额 == 贷方总额。"""
        debit = sum((float(l.debit) or 0) for l in self.lines)
        credit = sum((float(l.credit) or 0) for l in self.lines)
        return abs(debit - credit) < 0.01

    def refresh_totals(self) -> None:
        """从明细行重算借贷总额。"""
        self.debit_total = sum((float(l.debit) or 0) for l in self.lines)
        self.credit_total = sum((float(l.credit) or 0) for l in self.lines)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "entry_no": self.entry_no,
            "journal_date": self.journal_date.isoformat() if self.journal_date else None,
            "status": self.status,
            "description": self.description,
            "reference_type": self.reference_type,
            "reference_id": self.reference_id,
            "debit_total": float(self.debit_total) if self.debit_total is not None else 0.0,
            "credit_total": float(self.credit_total) if self.credit_total is not None else 0.0,
            "reversed_of_id": self.reversed_of_id,
            "reversed_at": self.reversed_at.isoformat() if self.reversed_at else None,
            "balanced": self.is_balanced(),
            "lines": [l.to_dict() for l in self.lines],
        }


class JournalEntryLine(IntegerPrimaryKeyMixin, TenantScopedMixin, Base):
    """记账凭证分录行（Odoo account.move.line 吸收：account_id/debit/credit/partner_id）。"""

    __tablename__ = "journal_entry_lines"

    entry_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("journal_entries.id"), nullable=False, index=True
    )
    account_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("chart_of_accounts.id"), nullable=True, index=True
    )
    account_code: Mapped[Optional[str]] = mapped_column(String(50))
    account_name: Mapped[Optional[str]] = mapped_column(String(200))
    debit: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), default=0)
    credit: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), default=0)
    partner_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    partner_name: Mapped[Optional[str]] = mapped_column(String(200))
    reference: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    entry: Mapped[Optional[JournalEntry]] = relationship("JournalEntry", back_populates="lines")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "entry_id": self.entry_id,
            "account_id": self.account_id,
            "account_code": self.account_code,
            "account_name": self.account_name,
            "debit": float(self.debit) if self.debit is not None else 0.0,
            "credit": float(self.credit) if self.credit is not None else 0.0,
            "partner_id": self.partner_id,
            "partner_name": self.partner_name,
            "reference": self.reference,
        }
