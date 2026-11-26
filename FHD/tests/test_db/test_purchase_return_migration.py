"""Old/fresh SQLite migration of approved receipt-bound supplier returns."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

_SOURCE_TABLES = (
    "purchase_inbounds", "purchase_inbound_items", "approval_requests",
    "journal_entries", "products", "suppliers", "warehouses", "storage_locations",
)


def _revision():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/2026_11_25_purchase_returns.py"
    spec = importlib.util.spec_from_file_location("purchase_returns_revision", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(conn, action="upgrade"):
    with Operations.context(MigrationContext.configure(conn)):
        getattr(_revision(), action)()


@pytest.fixture
def old_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-purchase.sqlite'}")
    with engine.begin() as conn:
        for table in _SOURCE_TABLES:
            conn.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
        conn.execute(text("INSERT INTO purchase_inbounds (id) VALUES (9)"))
        conn.execute(text("INSERT INTO purchase_inbound_items (id) VALUES (11)"))
        conn.execute(text("INSERT INTO approval_requests (id) VALUES (13)"))
        conn.execute(text("INSERT INTO journal_entries (id) VALUES (17)"))
        conn.execute(text("INSERT INTO products (id) VALUES (21)"))
        conn.execute(text("INSERT INTO suppliers (id) VALUES (23)"))
        conn.execute(text("INSERT INTO warehouses (id) VALUES (25)"))
    try:
        yield engine
    finally:
        engine.dispose()


def test_old_database_migrates_without_touching_original_documents(old_database):
    with old_database.begin() as conn:
        _run(conn)
        _run(conn)
        assert inspect(conn).has_table("purchase_returns")
        assert inspect(conn).has_table("purchase_return_items")
        for name, row_id in (
            ("purchase_inbounds", 9), ("purchase_inbound_items", 11),
            ("approval_requests", 13), ("journal_entries", 17),
        ):
            assert conn.execute(text(f"SELECT id FROM {name}")).scalar_one() == row_id
        conn.execute(text(
            "INSERT INTO purchase_returns "
            "(tenant_id, return_no, approval_request_id, inbound_id, supplier_id, "
            "warehouse_id, total_amount, status, posted_at) "
            "VALUES (3, 'RET-1', 13, 9, 23, 25, 3.50, 'posted', '2026-11-25')"
        ))
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(text(
                "INSERT INTO purchase_returns "
                "(tenant_id, return_no, approval_request_id, inbound_id, supplier_id, "
                "warehouse_id, total_amount, status, posted_at) "
                "VALUES (3, 'RET-1', 13, 9, 23, 25, 3.50, 'posted', '2026-11-25')"
            ))
        with pytest.raises(RuntimeError, match="refusing to erase"):
            _run(conn, "downgrade")
        assert conn.execute(text("SELECT count(*) FROM purchase_returns")).scalar_one() == 1


def test_partial_legacy_schema_refuses_lossy_recovery(old_database):
    with old_database.begin() as conn:
        conn.execute(text("CREATE TABLE purchase_returns (id INTEGER PRIMARY KEY, marker TEXT)"))
        conn.execute(text("INSERT INTO purchase_returns VALUES (1, 'original-data')"))
        with pytest.raises(RuntimeError, match="partial purchase return schema"):
            _run(conn)
        assert conn.execute(text("SELECT marker FROM purchase_returns")).scalar_one() == (
            "original-data"
        )


def test_new_orm_initialized_schema_not_recreated(tmp_path):
    import app.db.models
    from app.db.db_base import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'fresh-purchase.sqlite'}")
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            assert inspect(conn).has_table("purchase_returns")
            assert inspect(conn).has_table("purchase_return_items")
            _run(conn)
            assert conn.execute(text("SELECT count(*) FROM purchase_returns")).scalar_one() == 0
            assert conn.execute(text("SELECT count(*) FROM purchase_return_items")).scalar_one() == 0
    finally:
        engine.dispose()


def test_empty_return_tables_can_downgrade_without_erasing_history(old_database):
    with old_database.begin() as conn:
        _run(conn)
        _run(conn, "downgrade")
        assert not inspect(conn).has_table("purchase_return_items")
        assert not inspect(conn).has_table("purchase_returns")
        assert conn.execute(text("SELECT id FROM purchase_inbounds")).scalar_one() == 9
