"""Test the real SKU migration against existing SQLite product rows."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


def _upgrade(conn):
    path = Path(__file__).resolve().parents[2] / "alembic/versions/2026_11_25_erp_sku_key.py"
    spec = importlib.util.spec_from_file_location("erp_sku_key", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with Operations.context(MigrationContext.configure(conn)):
        migration.upgrade()


@pytest.fixture
def engine(tmp_path):
    db = create_engine(f"sqlite:///{tmp_path / 'sku.sqlite'}")
    with db.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE products (id INTEGER PRIMARY KEY, tenant_id INTEGER, "
                "unit TEXT, model_number TEXT, specification TEXT)"
            )
        )
    yield db
    db.dispose()


def _insert(conn, tenant, unit, sku, spec):
    conn.execute(
        text(
            "INSERT INTO products (tenant_id, unit, model_number, specification) "
            "VALUES (:t, :u, :s, :p)"
        ),
        {"t": tenant, "u": unit, "s": sku, "p": spec},
    )


def test_sku_identity_preserves_different_customers_tenants_and_unknown_models(engine):
    with engine.begin() as conn:
        _insert(conn, 1, "客户甲", "SKU-1", "原规格")
        _insert(conn, 1, "客户乙", "SKU-1", "乙规格")
        _insert(conn, 2, "客户甲", "SKU-1", "其他企业")
        _insert(conn, 1, "客户甲", None, "未知一")
        _insert(conn, 1, "客户甲", "", "未知二")
        _upgrade(conn)
        _upgrade(conn)
        with pytest.raises(IntegrityError), conn.begin_nested():
            _insert(conn, 1, " 客户甲 ", " sku-1 ", "禁止覆盖原规格")
        assert conn.execute(text("SELECT count(*) FROM products")).scalar_one() == 5
        assert (
            conn.execute(text("SELECT specification FROM products WHERE id=1")).scalar_one()
            == "原规格"
        )


def test_conflicting_sku_history_blocks_without_merging_specifications(engine):
    with engine.begin() as conn:
        _insert(conn, 1, "客户甲", "X", "规格A")
        _insert(conn, 1, "客户甲", "x", "规格B")
        with pytest.raises(RuntimeError, match="historical SKU conflict"):
            _upgrade(conn)
        assert conn.execute(text("SELECT count(*) FROM products")).scalar_one() == 2
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM sqlite_master WHERE type='index' AND name='uq_products_tenant_unit_sku'"
                )
            ).scalar_one()
            == 0
        )
