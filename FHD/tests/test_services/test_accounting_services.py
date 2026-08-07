"""
财务冲销/账龄/科目初始化服务测试（Task 5, upgrade-erp-modules-odoo18）

覆盖 app/services/accounting_services.py：
- seed_default_chart_of_accounts 幂等种入默认科目
- journal_entry_reverse 反向冲销（借贷平衡、原凭证标记、重复冲销拒绝）
- aging_report 应收/应付账龄分组

用真实 sqlite :memory:，并通过 patch 覆盖 accounting_services.get_db 指向内存库。
多租户过滤：用 tenant_scope(1) 提供租户上下文。
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import ChartOfAccount, JournalEntry
from app.infrastructure.tenant_scope import tenant_scope
from app.services import accounting_services as svc


@pytest.fixture(scope="function")
def db_session():
    """真实 sqlite 内存库会话。"""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _override_get_db(monkeypatch, db_session):
    """把 accounting_services.get_db 覆盖为返回内存库会话。"""

    @contextmanager
    def _get_db():
        yield db_session

    monkeypatch.setattr(svc, "get_db", _get_db)
    yield


def _create_entry(source_id: int, journal_date: date, partner_id: int, amount: float) -> JournalEntry:
    """创建一个『借应收 / 贷主营业务收入』的销售凭证（含 partner，供账龄/冲销用）。"""
    result = svc.create_journal_entry(
        {
            "journal_date": journal_date,
            "status": "posted",
            "description": f"销售-{source_id}",
            "reference_type": "sale",
            "reference_id": source_id,
            "lines": [
                {
                    "account_code": "1122",
                    "partner_id": partner_id,
                    "partner_name": "客户A",
                    "debit": amount,
                    "credit": 0,
                },
                {
                    "account_code": "6001",
                    "debit": 0,
                    "credit": amount,
                },
            ],
        }
    )
    assert result["success"] is True, result.get("message")
    return result["data"]


class TestSeedDefaultChartOfAccounts:
    def test_seed_idempotent(self, db_session):
        """种子幂等：跑两次不重复，首次新增 8 个。"""
        with tenant_scope(1):
            first = svc.seed_default_chart_of_accounts()
            assert first["success"] is True
            assert first["created"] == 8

            second = svc.seed_default_chart_of_accounts()
            assert second["success"] is True
            assert second["created"] == 0

            count = db_session.query(ChartOfAccount).count()
            assert count == 8

    def test_seed_codes_present(self, db_session):
        """默认科目 code 齐全且类型正确。"""
        with tenant_scope(1):
            svc.seed_default_chart_of_accounts()
            payable = (
                db_session.query(ChartOfAccount)
                .filter(ChartOfAccount.code == "2201")
                .first()
            )
            assert payable is not None
            assert payable.type == "liability"
            assert payable.debit_credit == "credit"


class TestJournalEntryReverse:
    def test_reverse_creates_balanced_entry(self, db_session):
        """冲销生成反向分录且借贷平衡、方向反转。"""
        with tenant_scope(1):
            svc.seed_default_chart_of_accounts()
            original = _create_entry(1, date.today() - timedelta(days=10), 100, 500.0)

            result = svc.journal_entry_reverse(original["id"])
            assert result["success"] is True, result.get("message")

            rev = result["data"]
            assert rev["status"] == "posted"
            assert rev["reference_type"] == "reversal"
            assert rev["reference_id"] == original["id"]
            assert rev["reversed_of_id"] == original["id"]
            assert rev["balanced"] is True
            assert rev["entry_no"] != original["entry_no"]
            # 方向反转：原借应收 500 → 冲销贷应收 500
            rev_lines = {l["account_code"]: l for l in rev["lines"]}
            assert rev_lines["1122"]["credit"] == 500.0
            assert rev_lines["1122"]["debit"] == 0.0
            assert rev_lines["6001"]["debit"] == 500.0
            assert rev_lines["6001"]["credit"] == 0.0

    def test_original_marked_reversed(self, db_session):
        """原凭证被标记为已冲销（reversed_at 非空）。"""
        with tenant_scope(1):
            svc.seed_default_chart_of_accounts()
            original = _create_entry(2, date.today() - timedelta(days=5), 100, 200.0)

            svc.journal_entry_reverse(original["id"])

            reloaded = db_session.query(JournalEntry).filter(JournalEntry.id == original["id"]).first()
            assert reloaded.reversed_at is not None

    def test_duplicate_reverse_rejected(self, db_session):
        """重复冲销被拒。"""
        with tenant_scope(1):
            svc.seed_default_chart_of_accounts()
            original = _create_entry(3, date.today() - timedelta(days=3), 100, 100.0)

            first = svc.journal_entry_reverse(original["id"])
            assert first["success"] is True

            second = svc.journal_entry_reverse(original["id"])
            assert second["success"] is False
            assert "已冲销" in second["message"]

    def test_reverse_missing_entry(self, db_session):
        """原凭证不存在返回失败。"""
        with tenant_scope(1):
            result = svc.journal_entry_reverse(999999)
            assert result["success"] is False


class TestAgingReport:
    def _seed_entries(self):
        svc.seed_default_chart_of_accounts()
        today = date.today()
        # 10 天前 → 0-30 桶
        _create_entry(10, today - timedelta(days=10), 200, 1000.0)
        # 45 天前 → 31-60 桶
        _create_entry(11, today - timedelta(days=45), 200, 2000.0)
        # 100 天前 → 90+ 桶
        _create_entry(12, today - timedelta(days=100), 200, 3000.0)

    def test_receivable_buckets(self, db_session):
        """应收账龄按账期分组输出。"""
        with tenant_scope(1):
            self._seed_entries()
            result = svc.aging_report("receivable", 200, as_of_date=date.today())
            assert result["success"] is True
            buckets = {b["bucket"]: b["amount"] for b in result["data"]}
            assert buckets["0-30"] == 1000.0
            assert buckets["31-60"] == 2000.0
            assert buckets["90+"] == 3000.0
            assert result["total_outstanding"] == 6000.0

    def test_invalid_party_type(self, db_session):
        """非法 party_type 返回失败。"""
        with tenant_scope(1):
            result = svc.aging_report("unknown", 200)
            assert result["success"] is False