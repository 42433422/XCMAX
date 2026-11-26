"""Exercise the actual identity migration on existing SQLite rows."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


def _revision():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/2026_11_25_erp_identity_keys.py"
    spec = importlib.util.spec_from_file_location("erp_identity_keys", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def engine(tmp_path):
    db = create_engine(f"sqlite:///{tmp_path / 'erp-identity.sqlite'}")
    with db.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE suppliers (id INTEGER PRIMARY KEY, tenant_id INTEGER, "
                "name TEXT NOT NULL, status TEXT)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE inventory_ledger (id INTEGER PRIMARY KEY, tenant_id INTEGER, "
                "product_id INTEGER NOT NULL, warehouse_id INTEGER NOT NULL, "
                "batch_no TEXT, location_id INTEGER, quantity NUMERIC)"
            )
        )
    yield db
    db.dispose()


def _upgrade(conn):
    with Operations.context(MigrationContext.configure(conn)):
        _revision().upgrade()


def _supplier(conn, tenant, name, status="active"):
    conn.execute(
        text("INSERT INTO suppliers (tenant_id, name, status) VALUES (:t, :n, :s)"),
        {"t": tenant, "n": name, "s": status},
    )


def _stock(conn, tenant, batch, location):
    conn.execute(
        text(
            "INSERT INTO inventory_ledger "
            "(tenant_id, product_id, warehouse_id, batch_no, location_id, quantity) "
            "VALUES (:t, 7, 9, :b, :l, 12)"
        ),
        {"t": tenant, "b": batch, "l": location},
    )


def test_supplier_upgrade_keeps_history_and_enforces_db_identity(engine):
    with engine.begin() as conn:
        _supplier(conn, 1, "Vendor")
        _supplier(conn, 2, " vendor ")
        _supplier(conn, 1, "Vendor", "deleted")
        _upgrade(conn)
        _upgrade(conn)
        assert conn.execute(text("SELECT count(*) FROM suppliers")).scalar_one() == 3
        for status in ("active", "inactive", None):
            with pytest.raises(IntegrityError), conn.begin_nested():
                _supplier(conn, 1, " VENDOR ", status)
        _supplier(conn, 1, "Vendor", "deleted")
        assert conn.execute(text("SELECT count(*) FROM suppliers")).scalar_one() == 4


@pytest.mark.parametrize("batch,location", [(None, None), ("A", None), (None, 3), ("A", 3)])
def test_physical_stock_key_covers_null_combinations(engine, batch, location):
    with engine.begin() as conn:
        _stock(conn, 1, batch, location)
        _stock(conn, 2, batch, location)
        _upgrade(conn)
        with pytest.raises(IntegrityError), conn.begin_nested():
            _stock(conn, 1, batch, location)
        assert conn.execute(text("SELECT sum(quantity) FROM inventory_ledger")).scalar_one() == 24


def test_history_conflict_blocks_before_any_index_or_data_change(engine):
    with engine.begin() as conn:
        _supplier(conn, 1, "Vendor")
        _stock(conn, 1, None, None)
        _stock(conn, 1, None, None)
        with pytest.raises(RuntimeError, match="historical identity conflict"):
            _upgrade(conn)
        assert conn.execute(text("SELECT count(*) FROM suppliers")).scalar_one() == 1
        assert conn.execute(text("SELECT sum(quantity) FROM inventory_ledger")).scalar_one() == 24
        assert (
            conn.execute(
                text("SELECT count(*) FROM sqlite_master WHERE type='index' AND name LIKE 'uq_%'")
            ).scalar_one()
            == 0
        )


def test_duplicate_supplier_history_is_not_merged(engine):
    with engine.begin() as conn:
        _supplier(conn, 1, "Vendor")
        _supplier(conn, 1, " vendor ")
        with pytest.raises(RuntimeError, match="uq_supplier_tenant_live_name"):
            _upgrade(conn)
        assert conn.execute(text("SELECT count(*) FROM suppliers")).scalar_one() == 2
