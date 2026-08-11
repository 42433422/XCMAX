from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import IntegerPrimaryKeyMixin, TenantScopedMixin, TimestampMixin

# 会计科目类型（Odoo account.account 吸收）
ACCOUNT_TYPES = {"asset", "liability", "equity", "revenue", "expense"}

# DB 级约束名（供迁移/测试引用，保持稳定）
CHART_OF_ACCOUNT_TYPE_CONSTRAINT = "ck_chart_of_accounts_type_in_account_types"
CHART_OF_ACCOUNT_DEBIT_CREDIT_CONSTRAINT = "ck_chart_of_accounts_debit_credit"
JOURNAL_ENTRY_IS_CREDIT_NOTE_CONSTRAINT = "ck_journal_entries_is_credit_note"
JOURNAL_ENTRY_LINE_NONNEGATIVE_CONSTRAINT = "ck_journal_entry_lines_nonnegative"
JOURNAL_ENTRY_LINE_NOT_BOTH_POSITIVE_CONSTRAINT = "ck_journal_entry_lines_not_both_positive"

# 由声明常量派生 SQL IN 子句，保证与 ACCOUNT_TYPES 同步
_ACCOUNT_TYPES_SQL = ", ".join(f"'{t}'" for t in sorted(ACCOUNT_TYPES))

# 已过账（posted）分录借贷平衡的 DB 级约束名
POSTED_BALANCED_CONSTRAINT = "ck_journal_entries_posted_balanced"


class ChartOfAccount(IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """会计科目表（Odoo account.account 吸收：code/name/type/debit_credit）。"""

    __tablename__ = "chart_of_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_chart_of_accounts_tenant_code"),
        CheckConstraint(
            f"type IN ({_ACCOUNT_TYPES_SQL})",
            name=CHART_OF_ACCOUNT_TYPE_CONSTRAINT,
        ),
        CheckConstraint(
            "debit_credit IN ('debit','credit')",
            name=CHART_OF_ACCOUNT_DEBIT_CREDIT_CONSTRAINT,
        ),
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False)
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
    """记账凭证（Odoo account.move 吸收：一组借贷平衡的 move.line）。

    - ``entry_no`` 改为 ``UniqueConstraint(tenant_id, entry_no)``（跨租户允许重复）。
    - 已过账（``status='posted'``）的分录借贷必平衡，由 DB 级
      ``ck_journal_entries_posted_balanced`` 约束强制（服务层 ``is_balanced()`` 仅为内存兜底）。
    """

    __tablename__ = "journal_entries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "entry_no", name="uq_journal_entries_tenant_entry_no"),
        CheckConstraint(
            "status != 'posted' OR ABS(COALESCE(debit_total,0) - COALESCE(credit_total,0)) < 0.01",
            name=POSTED_BALANCED_CONSTRAINT,
        ),
        CheckConstraint(
            "is_credit_note IN (0,1)",
            name=JOURNAL_ENTRY_IS_CREDIT_NOTE_CONSTRAINT,
        ),
    )

    entry_no: Mapped[str] = mapped_column(String(50), nullable=False)
    journal_date: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    reference_type: Mapped[Optional[str]] = mapped_column(String(64))
    reference_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    debit_total: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), default=0)
    credit_total: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), default=0)
    # 反向/冲销：被冲销的原始凭证为 reversed_of（冲销凭证记录），原凭证用 reversed_at 时间戳标记已冲销
    reversed_of_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("journal_entries.id", name="fk_journal_entries_reversed_of_id_journal_entries"),
        nullable=True,
        index=True,
    )
    reversed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # credit-note 关联：本凭证若为贷项通知单（credit note），记录其来源销售凭证；标记是否贷项
    credit_note_of_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey(
            "journal_entries.id", name="fk_journal_entries_credit_note_of_id_journal_entries"
        ),
        nullable=True,
        index=True,
    )
    is_credit_note: Mapped[int] = mapped_column(Integer, default=0)

    lines: Mapped[list[JournalEntryLine]] = relationship(
        "JournalEntryLine", back_populates="entry", cascade="all, delete-orphan", lazy="selectin"
    )

    def is_balanced(self) -> bool:
        """借贷平衡校验：借方总额 == 贷方总额（Decimal 求和，无浮点转换）。"""
        debit = sum((l.debit or Decimal(0)) for l in self.lines)
        credit = sum((l.credit or Decimal(0)) for l in self.lines)
        return abs(debit - credit) < Decimal("0.01")

    def refresh_totals(self) -> None:
        """从明细行重算借贷总额（Decimal 精度保留，赋值 Decimal 总计）。"""
        self.debit_total = sum((l.debit or Decimal(0)) for l in self.lines)
        self.credit_total = sum((l.credit or Decimal(0)) for l in self.lines)

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
            "credit_note_of_id": self.credit_note_of_id,
            "is_credit_note": self.is_credit_note,
            "balanced": self.is_balanced(),
            "lines": [l.to_dict() for l in self.lines],
        }


class JournalEntryLine(IntegerPrimaryKeyMixin, TenantScopedMixin, Base):
    """记账凭证分录行（Odoo account.move.line 吸收：account_id/debit/credit/partner_id）。"""

    __tablename__ = "journal_entry_lines"
    __table_args__ = (
        CheckConstraint(
            "COALESCE(debit,0) >= 0 AND COALESCE(credit,0) >= 0",
            name=JOURNAL_ENTRY_LINE_NONNEGATIVE_CONSTRAINT,
        ),
        CheckConstraint(
            "NOT (COALESCE(debit,0) > 0 AND COALESCE(credit,0) > 0)",
            name=JOURNAL_ENTRY_LINE_NOT_BOTH_POSITIVE_CONSTRAINT,
        ),
    )

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
