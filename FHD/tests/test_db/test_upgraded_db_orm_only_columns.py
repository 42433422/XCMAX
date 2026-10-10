"""Upgraded databases must reach the same customer/finance columns as fresh installs.

Windows U8 acceptance (2026-10-10): a customer database upgraded from an older
release was stamped at head but lacked ``customers.credit_limit`` /
``credit_used`` / ``is_credit_limited`` and ``financial_transactions.journal_entry_id``.
Fresh installs receive them from ``create_all``; the squashed baseline never alters
existing tables.  Sales closed-loop approval returned 409 and the finance
receivables / transactions APIs returned 500.

These tests rebuild that upgraded shape on a throwaway SQLite database, run the
real Alembic chain (and the desktop startup path), and compare the result with a
fresh ``create_all`` schema.
"""

from __future__ import annotations

import os
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.orm import Session

from alembic import command
from app.desktop_runtime import migrate
from app.desktop_runtime.paths import ensure_desktop_dirs

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _PROJECT_ROOT / "alembic.ini"
_PRE_REPAIR_HEAD = "2026_09_27_tenant_rbac_owner"
_REPAIR_REVISION = "2026_10_10_credit_journal_cols"
_REPAIRED_TABLES = ("customers", "financial_transactions")
_MISSING = {
    "customers": ("credit_limit", "credit_used", "is_credit_limited"),
    "financial_transactions": ("journal_entry_id",),
}


@pytest.fixture(autouse=True)
def _isolate_env():
    snapshot = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(snapshot)


def _url(db: Path) -> str:
    return "sqlite:///" + db.as_posix()


def _upgrade(db: Path, target: str = "head") -> None:
    os.environ["DATABASE_URL"] = _url(db)
    command.upgrade(Config(str(_ALEMBIC_INI)), target)


def _make_upgraded_style_db(db: Path) -> None:
    """Head-stamped DB without the ORM-only columns, holding legacy rows."""
    _upgrade(db, _PRE_REPAIR_HEAD)
    conn = sqlite3.connect(str(db))
    try:
        with conn:
            conn.execute("DROP INDEX IF EXISTS ix_financial_transactions_journal_entry_id")
            for table, columns in _MISSING.items():
                for column in columns:
                    conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
            conn.execute(
                "INSERT INTO customers (customer_name, tenant_id, created_at, updated_at) "
                "VALUES ('Legacy Customer', 1, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
            conn.execute(
                "INSERT INTO financial_transactions (transaction_type, amount, currency, "
                "transaction_date, status, created_at, updated_at, tenant_id) VALUES "
                "('receivable', 120.50, 'CNY', '2026-01-02 00:00:00', 'pending', "
                "'2026-01-02 00:00:00', '2026-01-02 00:00:00', 1)"
            )
        stamped = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        assert stamped == _PRE_REPAIR_HEAD
    finally:
        conn.close()


def _columns(db: Path, table: str) -> dict[str, dict]:
    engine = sa.create_engine(_url(db))
    try:
        return {row["name"]: row for row in sa.inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


def _indexes(db: Path, table: str) -> set[str]:
    engine = sa.create_engine(_url(db))
    try:
        return {str(row["name"]) for row in sa.inspect(engine).get_indexes(table)}
    finally:
        engine.dispose()


def _fresh_create_all_db(db: Path) -> None:
    import app.db.models  # noqa: F401
    from app.db.base import Base

    engine = sa.create_engine(_url(db))
    try:
        Base.metadata.create_all(
            engine, tables=[Base.metadata.tables[name] for name in _REPAIRED_TABLES]
        )
    finally:
        engine.dispose()


def _assert_matches_fresh(repaired: Path, fresh: Path) -> None:
    for table in _REPAIRED_TABLES:
        got = _columns(repaired, table)
        want = _columns(fresh, table)
        assert set(want) <= set(got), (table, sorted(set(want) - set(got)))
        for name in _MISSING[table]:
            assert type(got[name]["type"]) is type(want[name]["type"]), (table, name)
            assert got[name]["nullable"] == want[name]["nullable"], (table, name)
            if isinstance(want[name]["type"], sa.Numeric):
                assert got[name]["type"].precision == want[name]["type"].precision
                assert got[name]["type"].scale == want[name]["type"].scale
    assert "ix_financial_transactions_journal_entry_id" in _indexes(
        repaired, "financial_transactions"
    )


def _assert_orm_queries_work(db: Path) -> None:
    import app.db.models  # noqa: F401
    from app.db.models.customer import Customer
    from app.db.models.finance import FinancialTransaction

    engine = sa.create_engine(_url(db))
    try:
        with Session(engine) as session:
            # Same query shape as the sales closed-loop customer resolution (was 409).
            customer = (
                session.query(Customer)
                .filter(Customer.customer_name == "Legacy Customer", Customer.tenant_id == 1)
                .one()
            )
            assert customer.credit_limit == Decimal("0")
            assert customer.credit_used == Decimal("0")
            assert customer.is_credit_limited == 0
            # Finance receivables / transactions list (was 500).
            rows = session.query(FinancialTransaction).filter_by(tenant_id=1).all()
            assert [row.journal_entry_id for row in rows] == [None]
            rows[0].journal_entry_id = 7
            customer.credit_limit = Decimal("5000.00")
            customer.is_credit_limited = 1
            session.commit()
            assert session.query(FinancialTransaction).one().to_dict()["journal_entry_id"] == 7
    finally:
        engine.dispose()


def test_upgraded_db_gets_missing_columns_like_fresh_install(tmp_path: Path) -> None:
    db = tmp_path / "upgraded.db"
    fresh = tmp_path / "fresh.db"
    _make_upgraded_style_db(db)
    _fresh_create_all_db(fresh)

    _upgrade(db)

    _assert_matches_fresh(db, fresh)
    _assert_orm_queries_work(db)


def test_repair_is_noop_when_rerun_and_on_complete_db(tmp_path: Path) -> None:
    db = tmp_path / "upgraded.db"
    _make_upgraded_style_db(db)
    _upgrade(db)
    before = {table: _columns(db, table) for table in _REPAIRED_TABLES}

    # Re-run the repair revision on an already repaired database.
    _upgrade(db, _PRE_REPAIR_HEAD)  # no-op: already past it
    command.downgrade(Config(str(_ALEMBIC_INI)), _PRE_REPAIR_HEAD)
    _upgrade(db)

    after = {table: _columns(db, table) for table in _REPAIRED_TABLES}
    assert {t: sorted(c) for t, c in after.items()} == {t: sorted(c) for t, c in before.items()}

    # A complete (fresh) chain is untouched as well.
    complete = tmp_path / "complete.db"
    _upgrade(complete)
    for table in _REPAIRED_TABLES:
        assert set(_MISSING[table]) <= set(_columns(complete, table))


def test_desktop_startup_repairs_upgraded_customer_db(tmp_path: Path) -> None:
    data_dir = tmp_path / "xcagi-home"
    db = ensure_desktop_dirs(data_dir)["data"] / "xcagi.db"
    _make_upgraded_style_db(db)

    result = migrate.ensure_startup_migration(str(data_dir))

    assert result["action"] == "upgraded"
    assert _REPAIR_REVISION in migrate._known_alembic_revisions()
    for table, columns in _MISSING.items():
        assert set(columns) <= set(_columns(db, table))
    _assert_orm_queries_work(db)
    # Pre-migration backup exists and still has the legacy shape for rollback.
    backups = sorted((data_dir / "backups").glob("xcagi-*.db"))
    assert len(backups) == 1
    assert "credit_limit" not in _columns(backups[0], "customers")
