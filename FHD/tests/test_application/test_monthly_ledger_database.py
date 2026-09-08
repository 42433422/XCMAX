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
