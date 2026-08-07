"""
财务复式记账模型（Double-entry）单元测试

覆盖 Task 3（absorb-odoo18-erp-agent）：
- ChartOfAccount 会计科目表
- JournalEntry/JournalEntryLine 借贷平衡分录
- 采购入库生成『借库存 / 贷应付账款』借贷平衡分录
- financial_transactions 与分录关联
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import (
    ACCOUNT_TYPES,
    ChartOfAccount,
    FinancialTransaction,
    JournalEntry,
    JournalEntryLine,
)


@pytest.fixture(scope="function")
def test_engine():
    return create_engine("sqlite:///:memory:")


@pytest.fixture(scope="function")
def test_session(test_engine):
    Base.metadata.create_all(test_engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _seed_chart(db):
    """种入库存(asset/借)与应付账款(liability/贷)科目。"""
    inventory = ChartOfAccount(code="1401", name="库存商品", type="asset", debit_credit="debit")
    payable = ChartOfAccount(code="2201", name="应付账款", type="liability", debit_credit="credit")
    db.add_all([inventory, payable])
    db.commit()
    db.refresh(inventory)
    db.refresh(payable)
    return inventory, payable


class TestChartOfAccount:
    def test_create_account(self, test_session):
        """创建会计科目。"""
        acc = ChartOfAccount(code="1001", name="库存现金", type="asset", debit_credit="debit")
        test_session.add(acc)
        test_session.commit()
        test_session.refresh(acc)
        assert acc.id is not None
        assert acc.code == "1001"
        assert acc.type == "asset"
        assert acc.debit_credit == "debit"

    def test_account_types(self):
        """科目类型集合包含标准五大类。"""
        assert {"asset", "liability", "equity", "revenue", "expense"} <= ACCOUNT_TYPES


class TestJournalEntry:
    def test_create_balanced_double_entry(self, test_session):
        """采购入库生成『借库存 / 贷应付账款』借贷平衡分录。"""
        inventory, payable = _seed_chart(test_session)
        entry = JournalEntry(
            entry_no="JE-2026-0001",
            journal_date=date(2026, 8, 3),
            status="posted",
            description="采购入库",
            reference_type="purchase_inbound",
            reference_id=1,
        )
        entry.lines.append(
            JournalEntryLine(
                account_id=inventory.id,
                account_code=inventory.code,
                account_name=inventory.name,
                debit=1000.0,
                credit=0,
            )
        )
        entry.lines.append(
            JournalEntryLine(
                account_id=payable.id,
                account_code=payable.code,
                account_name=payable.name,
                debit=0,
                credit=1000.0,
                partner_name="供应商A",
            )
        )
        test_session.add(entry)
        test_session.commit()
        test_session.refresh(entry)

        assert entry.is_balanced() is True
        assert len(entry.lines) == 2
        assert entry.debit_total is None or not entry.debit_total  # 未刷新

        # 刷新借贷总额
        entry.refresh_totals()
        assert entry.debit_total == 1000.0
        assert entry.credit_total == 1000.0

    def test_unbalanced_entry_rejected(self, test_session):
        """借贷不等的分录 is_balanced 为 False。"""
        inventory, _ = _seed_chart(test_session)
        entry = JournalEntry(entry_no="JE-2026-0002", journal_date=date(2026, 8, 3))
        entry.lines.append(
            JournalEntryLine(
                account_id=inventory.id, account_code=inventory.code, debit=100.0, credit=0
            )
        )
        entry.lines.append(
            JournalEntryLine(
                account_id=inventory.id, account_code=inventory.code, debit=0, credit=90.0
            )
        )
        test_session.add(entry)
        test_session.commit()
        assert entry.is_balanced() is False

    def test_financial_transaction_links_journal(self, test_session):
        """financial_transactions 与分录通过 journal_entry_id 关联。"""
        inventory, payable = _seed_chart(test_session)
        entry = JournalEntry(
            entry_no="JE-2026-0003",
            journal_date=date(2026, 8, 3),
            status="posted",
            reference_type="purchase_inbound",
            reference_id=2,
        )
        entry.lines.append(
            JournalEntryLine(account_id=inventory.id, account_code=inventory.code, debit=1000.0)
        )
        entry.lines.append(
            JournalEntryLine(account_id=payable.id, account_code=payable.code, credit=1000.0)
        )
        test_session.add(entry)
        test_session.commit()
        test_session.refresh(entry)

        txn = FinancialTransaction(
            transaction_type="purchase_inbound",
            amount=1000.0,
            currency="CNY",
            reference_type="purchase_inbound",
            reference_id=2,
            journal_entry_id=entry.id,
            status="posted",
        )
        test_session.add(txn)
        test_session.commit()
        test_session.refresh(txn)

        assert txn.journal_entry_id == entry.id
        assert txn.to_dict()["journal_entry_id"] == entry.id


class TestJournalEntryToDict:
    def test_to_dict_includes_lines(self, test_session):
        """序列化含行明细与借贷总额。"""
        inventory, payable = _seed_chart(test_session)
        entry = JournalEntry(entry_no="JE-2026-0004", journal_date=date(2026, 8, 3))
        entry.lines.append(
            JournalEntryLine(account_code=inventory.code, account_name=inventory.name, debit=500.0)
        )
        entry.lines.append(
            JournalEntryLine(account_code=payable.code, account_name=payable.name, credit=500.0)
        )
        test_session.add(entry)
        test_session.commit()
        test_session.refresh(entry)
        entry.refresh_totals()

        d = entry.to_dict()
        assert d["balanced"] is True
        assert d["debit_total"] == 500.0
        assert d["credit_total"] == 500.0
        assert len(d["lines"]) == 2
