"""Execute the candidate Alembic migration against real temporary SQLite files."""

import importlib.util
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from alembic import command

SOURCE = Path(__file__).resolve().parents[2] / "alembic/versions/2026_10_20_receipt_identity.py"
spec = importlib.util.spec_from_file_location("candidate_migration", SOURCE)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def apply(connection, fn):
    with Operations.context(MigrationContext.configure(connection)):
        fn()


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'literal%name.db'}")
    yield engine
    engine.dispose()


@pytest.fixture
def legacy_engine(engine):
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE receivable_allocations "
                "(id INTEGER PRIMARY KEY, sales_order_id INTEGER, amount NUMERIC(18,2))"
            )
        )
        connection.execute(text("INSERT INTO receivable_allocations VALUES (1, 7, 500)"))
    return engine


def test_upgrade_keeps_old_receipts_and_is_repeatable(legacy_engine):
    engine = legacy_engine
    with engine.begin() as connection:
        apply(connection, migration.upgrade)
        apply(connection, migration.upgrade)
        receipt = connection.execute(
            text(
                "SELECT amount, request_key, request_fingerprint "
                "FROM receivable_allocations WHERE id=1"
            )
        ).one()
        assert receipt == (500, None, None)
        indexes = inspect(connection).get_indexes("receivable_allocations")
        assert any(
            row["name"] == "uq_receivable_order_request" and row["unique"] for row in indexes
        )
        assert "web_refresh_token_uses" in inspect(connection).get_table_names()


def test_payment_identity_unique_index_is_enforced(legacy_engine):
    engine = legacy_engine
    with engine.begin() as connection:
        apply(connection, migration.upgrade)
        connection.execute(
            text(
                "INSERT INTO receivable_allocations (id, sales_order_id, amount, request_key) "
                "VALUES (2, 7, 500, 'same')"
            )
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO receivable_allocations (id, sales_order_id, amount, request_key) "
                "VALUES (3, 7, 500, 'same')"
            )
        )


def test_downgrade_preserves_used_token_identity(legacy_engine):
    engine = legacy_engine
    with engine.begin() as connection:
        apply(connection, migration.upgrade)
        connection.execute(text("INSERT INTO web_refresh_token_uses VALUES ('used', 2000000000)"))
        apply(connection, migration.downgrade)
        assert (
            connection.execute(text("SELECT jti FROM web_refresh_token_uses")).scalar_one()
            == "used"
        )


def test_missing_baseline_fails_explicitly(engine, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", str(engine.url))
    config = Config()
    config.set_main_option("script_location", str(SOURCE.parents[1]))
    command.current(config)  # A literal percent in a valid URL must not be interpolated.
    with pytest.raises(RuntimeError, match="baseline"), engine.begin() as connection:
        apply(connection, migration.upgrade)
