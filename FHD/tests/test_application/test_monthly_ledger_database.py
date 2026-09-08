"""Monthly ledger boundaries and tenant isolation with real SQL queries."""

from contextlib import contextmanager
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.workflow.finance_query import monthly_ledger_node
from app.db.models import ChartOfAccount, JournalEntry, JournalEntryLine
from app.infrastructure.tenant_scope import tenant_scope
from app.services import accounting_services


def test_monthly_ledger_reads_only_month_and_tenant_without_writes(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'ledger.sqlite'}")
    factory = sessionmaker(bind=engine)
    for model in (ChartOfAccount, JournalEntry, JournalEntryLine):
        model.__table__.create(engine)
    with factory.begin() as db:
        for entry_id, tenant_id, day in [
            (1, 7, date(2024, 1, 31)),
            (2, 7, date(2024, 2, 1)),
            (3, 7, date(2024, 2, 29)),
            (4, 7, date(2024, 3, 1)),
            (5, 8, date(2024, 2, 15)),
        ]:
            db.add(
                JournalEntry(
                    id=entry_id,
                    tenant_id=tenant_id,
                    entry_no=f"E{entry_id}",
                    journal_date=day,
                    status="posted",
                )
            )

    @contextmanager
    def isolated_db():
        with factory() as db:
            yield db

    monkeypatch.setattr(accounting_services, "get_db", isolated_db)
    node = monthly_ledger_node("查询这个月的账本", today=date(2024, 2, 20))
    with tenant_scope(7):
        result = accounting_services.query_financial_ledger(**node.params)
        assert result["success"] and result["total"] == 2
        assert [row["id"] for row in result["data"]] == [3, 2]
        for page, expected in [(1, 3), (2, 2)]:
            paged = accounting_services.query_financial_ledger(
                **{**node.params, "per_page": 1, "page": page}
            )
            assert paged["total"] == 2
            assert [row["id"] for row in paged["data"]] == [expected]
        with factory() as db:
            assert db.query(JournalEntry).count() == 4
    with tenant_scope(8):
        other = accounting_services.query_financial_ledger(**node.params)
        assert [row["id"] for row in other["data"]] == [5]
        with factory() as db:
            assert db.query(JournalEntry).count() == 1
    engine.dispose()


def test_account_ledger_paginates_matching_lines_before_limiting(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'account.sqlite'}")
    factory = sessionmaker(bind=engine)
    for model in (ChartOfAccount, JournalEntry, JournalEntryLine):
        model.__table__.create(engine)
    with factory.begin() as db:
        db.add(ChartOfAccount(id=1, tenant_id=7, code="1001", name="现金"))
        for entry_id in (1, 2, 3):
            db.add(
                JournalEntry(
                    id=entry_id,
                    tenant_id=7,
                    entry_no=f"E{entry_id}",
                    journal_date=date(2024, 2, entry_id),
                )
            )
        db.add(ChartOfAccount(id=2, tenant_id=8, code="1001", name="另一租户现金"))
        db.add(JournalEntry(id=4, tenant_id=8, entry_no="OTHER", journal_date=date(2024, 2, 4)))
        db.flush()
        db.add(
            JournalEntryLine(
                id=5, tenant_id=8, entry_id=4, account_id=2, account_code="1001", debit=99
            )
        )
        # A malformed cross-tenant reference must not leak either entity.
        db.add(
            JournalEntryLine(
                id=6, tenant_id=8, entry_id=2, account_id=2, account_code="1001", debit=98
            )
        )
        for line_id, entry_id, code in [
            (1, 1, "1001"),
            (2, 2, "1001"),
            (3, 2, "1001"),
            (4, 3, "2001"),
        ]:
            db.add(
                JournalEntryLine(
                    id=line_id,
                    tenant_id=7,
                    entry_id=entry_id,
                    account_id=1 if code == "1001" else None,
                    account_code=code,
                    debit=line_id,
                )
            )

    @contextmanager
    def isolated_db():
        with factory() as db:
            yield db

    monkeypatch.setattr(accounting_services, "get_db", isolated_db)
    with tenant_scope(7):
        for selector in ({"account_id": 1}, {"account_code": "1001"}):
            for page, expected in [(1, [3.0]), (2, [2.0]), (3, [1.0]), (4, [])]:
                result = accounting_services.query_financial_ledger(
                    **selector, page=page, per_page=1
                )
                assert result["success"] and result["total"] == 3
                assert [line["debit"] for line in result["data"]] == expected
    with tenant_scope(8):
        assert not accounting_services.query_financial_ledger(account_id=1)["success"]
        other = accounting_services.query_financial_ledger(account_code="1001")
        assert other["total"] == 1
        assert [line["debit"] for line in other["data"]] == [99.0]
    engine.dispose()
