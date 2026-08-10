"""ODOO-W1-01 ERP 正交 schema 迁移测试。

覆盖：
- ``Base.metadata`` 含全部新增表（含 receivable_allocations）。
- fresh bootstrap（一次性临时库）建出这些表（仅作 fresh create 兜底）。
- 既有 schema 的升级仍运行 ``alembic upgrade head``（bootstrap 不接管既有库升级）。
- forward upgrade / backfill 保留既有数据；downgrade -1 后可再次 upgrade head（幂等一致）。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from alembic import command

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _PROJECT_ROOT / "alembic.ini"

_ERP_TABLES = {
    "sales_orders",
    "sales_order_items",
    "chart_of_accounts",
    "journal_entries",
    "journal_entry_lines",
    "products",
    "inventory_transactions",
    "receivable_allocations",
    "uom_categories",
    "uom_units",
}

# ensure_erp_bootstrap（fresh create 兜底）负责建出的表集合
_BOOTSTRAP_ERP_TABLES = {
    "sales_orders",
    "sales_order_items",
    "chart_of_accounts",
    "journal_entries",
    "journal_entry_lines",
    "receivable_allocations",
    "uom_categories",
    "uom_units",
}


def _alembic_config() -> Config:
    return Config(str(_ALEMBIC_INI))


@pytest.fixture()
def _db_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """返回一次性 SQLite 库 URL，并注入 DATABASE_URL（env.py 读取）。"""
    url = f"sqlite:///{tmp_path / 'erp_schema.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    return url


def _tables(url: str) -> set[str]:
    from sqlalchemy import create_engine, inspect

    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _columns(url: str, table: str) -> set[str]:
    from sqlalchemy import create_engine, inspect

    engine = create_engine(url)
    try:
        insp = inspect(engine)
        if table not in insp.get_table_names():
            return set()
        return {str(c["name"]) for c in insp.get_columns(table)}
    finally:
        engine.dispose()


def _unique_constraint_names(url: str, table: str) -> set[str]:
    from sqlalchemy import create_engine, inspect

    engine = create_engine(url)
    try:
        insp = inspect(engine)
        if table not in insp.get_table_names():
            return set()
        return {str(c["name"]) for c in insp.get_unique_constraints(table)}
    finally:
        engine.dispose()


def _column_nullable(url: str, table: str, column: str) -> bool | None:
    from sqlalchemy import create_engine, inspect

    engine = create_engine(url)
    try:
        insp = inspect(engine)
        if table not in insp.get_table_names():
            return None
        for c in insp.get_columns(table):
            if c["name"] == column:
                return c["nullable"]
        return None
    finally:
        engine.dispose()


def _foreign_keys(url: str, table: str) -> list[dict]:
    from sqlalchemy import create_engine, inspect

    engine = create_engine(url)
    try:
        insp = inspect(engine)
        if table not in insp.get_table_names():
            return []
        return insp.get_foreign_keys(table)
    finally:
        engine.dispose()


def _fk_engine(url: str):
    """SQLite 引擎，连接时显式开启 ``PRAGMA foreign_keys=ON``（SQLite 默认关闭）。"""
    from sqlalchemy import create_engine

    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def _check_constraint_names(url: str, table: str) -> set[str]:
    from sqlalchemy import create_engine, inspect

    engine = create_engine(url)
    try:
        insp = inspect(engine)
        if table not in insp.get_table_names():
            return set()
        return {str(c["name"]) for c in insp.get_check_constraints(table) if c.get("name")}
    finally:
        engine.dispose()


def _indexes(url: str, table: str) -> list[dict]:
    from sqlalchemy import create_engine, inspect

    engine = create_engine(url)
    try:
        insp = inspect(engine)
        if table not in insp.get_table_names():
            return []
        return insp.get_indexes(table)
    finally:
        engine.dispose()


class TestBaseMetadataRegistration:
    def test_base_metadata_contains_all_erp_tables(self) -> None:
        from app.db.base import Base

        names = {t.name for t in Base.metadata.sorted_tables}
        assert names >= _ERP_TABLES

    def test_receivable_allocation_registered(self) -> None:
        from app.db.base import Base
        from app.db.models import ReceivableAllocation

        assert "receivable_allocations" in {t.name for t in Base.metadata.sorted_tables}
        assert ReceivableAllocation.__tablename__ == "receivable_allocations"


class TestAlembicForwardUpgrade:
    def test_upgrade_head_creates_schema(self, _db_url: str) -> None:
        command.upgrade(_alembic_config(), "head")
        tables = _tables(_db_url)
        assert tables >= _ERP_TABLES

        # 正交维度字段
        sales_cols = _columns(_db_url, "sales_orders")
        assert {
            "state",
            "invoice_status",
            "payment_state",
            "backorder_of_id",
            "return_of_id",
        } <= sales_cols
        item_cols = _columns(_db_url, "sales_order_items")
        assert {"reserved_quantity", "returned_quantity"} <= item_cols
        product_cols = _columns(_db_url, "products")
        assert {
            "base_uom_id",
            "uom_category",
            "uom_factor",
            "min_stock",
            "max_stock",
        } <= product_cols
        inv_cols = _columns(_db_url, "inventory_transactions")
        assert {"ordered_quantity", "delivered_quantity", "sales_order_id"} <= inv_cols
        # 履行维度：两个销售外键 + 两个索引 + 三个数量 CHECK
        inv_fks = _foreign_keys(_db_url, "inventory_transactions")
        assert {
            (
                tuple(fk.get("constrained_columns") or []),
                fk.get("referred_table"),
                tuple(fk.get("referred_columns") or []),
            )
            for fk in inv_fks
        } >= {
            (("sales_order_id",), "sales_orders", ("id",)),
            (("sales_order_item_id",), "sales_order_items", ("id",)),
        }
        assert {
            "ix_inventory_transactions_sales_order_id",
            "ix_inventory_transactions_sales_order_item_id",
        } <= {i["name"] for i in _indexes(_db_url, "inventory_transactions")}
        assert {
            "ck_inventory_transactions_ordered_quantity_nonnegative",
            "ck_inventory_transactions_delivered_quantity_nonnegative",
            "ck_inventory_transactions_delivered_not_exceed_ordered",
        } <= _check_constraint_names(_db_url, "inventory_transactions")
        je_cols = _columns(_db_url, "journal_entries")
        assert {"credit_note_of_id", "is_credit_note"} <= je_cols

        # UOM：uom_categories/uom_units 表 + 列 + 约束
        uomcat_cols = _columns(_db_url, "uom_categories")
        assert {"code", "name"} <= uomcat_cols
        uomunit_cols = _columns(_db_url, "uom_units")
        assert {"category_id", "code", "name", "factor", "is_reference"} <= uomunit_cols
        assert "uq_uom_categories_tenant_code" in _unique_constraint_names(
            _db_url, "uom_categories"
        )
        assert "uq_uom_units_tenant_category_code" in _unique_constraint_names(_db_url, "uom_units")

        # UOM 结构性断言：category_id / factor 非空
        assert _column_nullable(_db_url, "uom_units", "category_id") is False
        assert _column_nullable(_db_url, "uom_units", "factor") is False
        # UOM category 结构 FK：uom_units.category_id → uom_categories.id（精确单 FK 匹配，
        # 重复/多余 FK 会导致 len != 1 而失败）
        uom_unit_fks = _foreign_keys(_db_url, "uom_units")
        assert len(uom_unit_fks) == 1
        assert list(uom_unit_fks[0].get("constrained_columns") or []) == ["category_id"]
        assert uom_unit_fks[0].get("referred_table") == "uom_categories"
        assert list(uom_unit_fks[0].get("referred_columns") or []) == ["id"]
        # 产品 base-UOM 结构 FK：products.base_uom_id → uom_units.id（精确单 FK 匹配）
        product_fks = _foreign_keys(_db_url, "products")
        assert len(product_fks) == 1
        assert list(product_fks[0].get("constrained_columns") or []) == ["base_uom_id"]
        assert product_fks[0].get("referred_table") == "uom_units"
        assert list(product_fks[0].get("referred_columns") or []) == ["id"]
        # 已实现的产品 base-UOM 索引
        assert "ix_products_base_uom_id" in {i["name"] for i in _indexes(_db_url, "products")}

        # 租户复合唯一约束（跨租户允许重复）
        assert "uq_sales_orders_tenant_order_no" in _unique_constraint_names(
            _db_url, "sales_orders"
        )
        assert "uq_chart_of_accounts_tenant_code" in _unique_constraint_names(
            _db_url, "chart_of_accounts"
        )
        assert "uq_journal_entries_tenant_entry_no" in _unique_constraint_names(
            _db_url, "journal_entries"
        )

    def test_upgrade_downgrade_upgrade_idempotent(self, _db_url: str) -> None:
        cfg = _alembic_config()
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "-1")
        # downgrade 仅删除本迁移新增的维度/约束，业务数据主体表保留
        assert "sales_orders" in _tables(_db_url)
        # 可再次 upgrade head（幂等一致）
        command.upgrade(cfg, "head")
        assert _tables(_db_url) >= _ERP_TABLES


class TestBootstrapIsFreshCreateFallback:
    def test_bootstrap_creates_tables_on_fresh_db(self, _db_url: str) -> None:
        from app.db.init_db import ensure_erp_bootstrap

        ensure_erp_bootstrap(engine=None, database_url=_db_url, swallow_errors=False)
        tables = _tables(_db_url)
        assert tables >= _BOOTSTRAP_ERP_TABLES

    def test_existing_schema_upgrade_runs_alembic(self, _db_url: str) -> None:
        """bootstrap 建出 fresh 表后，既有 schema 升级仍走 alembic upgrade head。"""
        from app.db.init_db import ensure_erp_bootstrap

        ensure_erp_bootstrap(engine=None, database_url=_db_url, swallow_errors=False)
        # 既有库升级走 Alembic（不依赖 bootstrap 做 ALTER）
        command.upgrade(_alembic_config(), "head")
        sales_cols = _columns(_db_url, "sales_orders")
        assert "state" in sales_cols


class TestBackfillPreservesData:
    def test_backfill_maps_legacy_status_to_dimensions(self, _db_url: str) -> None:
        from sqlalchemy import create_engine, text

        # 用旧 schema 形态手工建销售订单，模拟存量数据
        engine = create_engine(_db_url)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE TABLE sales_orders ("
                        " id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id INTEGER,"
                        " order_no VARCHAR(50), status VARCHAR(20),"
                        " quote_date DATE, confirm_date DATE,"
                        " total_amount NUMERIC(18,2), paid_amount NUMERIC(18,2),"
                        " currency VARCHAR(8), remark TEXT,"
                        " created_at DATETIME, updated_at DATETIME)"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO sales_orders (order_no, status, total_amount) "
                        "VALUES (:no, :status, :amount)"
                    ),
                    {"no": "SO-OLD-001", "status": "paid", "amount": 100},
                )
        finally:
            engine.dispose()

        command.upgrade(_alembic_config(), "head")

        engine = create_engine(_db_url)
        try:
            with engine.connect() as conn:
                row = (
                    conn.execute(
                        text("SELECT state, invoice_status, payment_state FROM sales_orders")
                    )
                    .mappings()
                    .first()
                )
                assert row is not None
                assert row["state"] == "confirmed"
                assert row["invoice_status"] == "invoiced"
                assert row["payment_state"] == "paid"
                # 既有数据保留
                total = conn.execute(text("SELECT total_amount FROM sales_orders")).scalar()
                assert float(total) == 100.0
        finally:
            engine.dispose()


class TestDatabaseConstraintRejection:
    """SQLite（Alembic head 真实库）DB 级约束拒绝测试。

    全部基于一次性 tmp 库（``_db_url`` fixture），仅校验约束/回滚行为，
    不触碰任何 repo 数据库。违反约束统一抛 ``IntegrityError``，事务随连接关闭回滚。
    """

    @staticmethod
    def _head_up(_db_url: str) -> None:
        command.upgrade(_alembic_config(), "head")

    @staticmethod
    def _insert_category(conn, tenant: int, code: str, name: str) -> int:
        return conn.execute(
            text(
                "INSERT INTO uom_categories (tenant_id, code, name, is_active) "
                "VALUES (:t, :code, :name, 1)"
            ),
            {"t": tenant, "code": code, "name": name},
        ).lastrowid

    def test_uom_unit_factor_zero_rejected(self, _db_url: str) -> None:
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                cat_id = self._insert_category(conn, 1, "wt", "Weight")
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO uom_units "
                            "(tenant_id, category_id, code, name, factor, is_reference, "
                            "is_active) VALUES (1, :cat, 'g', 'gram', 0, 0, 1)"
                        ),
                        {"cat": cat_id},
                    )
        finally:
            engine.dispose()

    def test_uom_unit_is_reference_outside_01_rejected(self, _db_url: str) -> None:
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                cat_id = self._insert_category(conn, 1, "wt", "Weight")
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO uom_units "
                            "(tenant_id, category_id, code, name, factor, is_reference, "
                            "is_active) VALUES (1, :cat, 'g', 'gram', 1, 2, 1)"
                        ),
                        {"cat": cat_id},
                    )
        finally:
            engine.dispose()

    def test_uom_unit_missing_category_rejected(self, _db_url: str) -> None:
        """category_id 指向不存在的类别 → FK 拒绝（需 PRAGMA foreign_keys=ON）。"""
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO uom_units "
                            "(tenant_id, category_id, code, name, factor, is_reference, "
                            "is_active) VALUES (1, :cat, 'g', 'gram', 1, 0, 1)"
                        ),
                        {"cat": 999999},
                    )
        finally:
            engine.dispose()

    def test_duplicate_uom_category_code_same_tenant_rejected(self, _db_url: str) -> None:
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                self._insert_category(conn, 1, "dup", "First")
                with pytest.raises(IntegrityError):
                    self._insert_category(conn, 1, "dup", "Second")
        finally:
            engine.dispose()

    def test_same_uom_category_code_across_tenants_succeeds(self, _db_url: str) -> None:
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                self._insert_category(conn, 1, "shared", "Tenant1")
                self._insert_category(conn, 2, "shared", "Tenant2")
                count = conn.execute(
                    text("SELECT COUNT(*) FROM uom_categories WHERE code = 'shared'")
                ).scalar_one()
                assert count == 2
        finally:
            engine.dispose()

    def test_product_uom_factor_zero_rejected(self, _db_url: str) -> None:
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO products "
                            "(tenant_id, name, unit, is_active, uom_factor) "
                            "VALUES (1, 'P', '个', 1, 0)"
                        )
                    )
        finally:
            engine.dispose()

    def test_product_min_stock_gt_max_stock_rejected(self, _db_url: str) -> None:
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO products "
                            "(tenant_id, name, unit, is_active, min_stock, max_stock) "
                            "VALUES (1, 'P', '个', 1, 10, 5)"
                        )
                    )
        finally:
            engine.dispose()


def _seed_product_and_warehouse(conn, tenant: int = 1) -> tuple[int, int]:
    """插入一个 product 与 warehouse，返回 (product_id, warehouse_id)。

    供 inventory_transactions 约束测试使用，使 FK（product/warehouse）通过，
    从而聚焦测试数量 CHECK 与销售外键约束。
    """
    conn.execute(
        text("INSERT INTO products (tenant_id, name, unit, is_active) VALUES (:t, 'P', '个', 1)"),
        {"t": tenant},
    )
    product_id = conn.execute(text("SELECT MAX(id) FROM products")).scalar_one()
    conn.execute(
        text(
            "INSERT INTO warehouses (tenant_id, code, name, status) "
            "VALUES (:t, 'WH01', 'WH', 'active')"
        ),
        {"t": tenant},
    )
    warehouse_id = conn.execute(text("SELECT MAX(id) FROM warehouses")).scalar_one()
    return product_id, warehouse_id


class TestInventoryTransactionConstraintRejection:
    """inventory_transactions 履行维度 DB 级约束拒绝测试（SQLite Alembic head 真实库）。"""

    @staticmethod
    def _head_up(_db_url: str) -> None:
        command.upgrade(_alembic_config(), "head")

    @staticmethod
    def _insert_txn(conn, product_id: int, warehouse_id: int, **overrides) -> None:
        base_cols = {
            "tenant_id": 1,
            "transaction_type": "out",
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "quantity": -1,
            "ordered_quantity": 5,
            "delivered_quantity": 3,
            "transaction_date": "2026-08-10",
        }
        base_cols.update(overrides)
        col_names = ", ".join(base_cols)
        placeholders = ", ".join(f":{k}" for k in base_cols)
        conn.execute(
            text(f"INSERT INTO inventory_transactions ({col_names}) VALUES ({placeholders})"),
            base_cols,
        )

    def test_delivered_exceeds_ordered_rejected(self, _db_url: str) -> None:
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                product_id, warehouse_id = _seed_product_and_warehouse(conn)
                with pytest.raises(IntegrityError):
                    self._insert_txn(conn, product_id, warehouse_id, delivered_quantity=6)
        finally:
            engine.dispose()

    def test_negative_delivered_rejected(self, _db_url: str) -> None:
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                product_id, warehouse_id = _seed_product_and_warehouse(conn)
                with pytest.raises(IntegrityError):
                    self._insert_txn(conn, product_id, warehouse_id, delivered_quantity=-1)
        finally:
            engine.dispose()

    def test_negative_ordered_rejected(self, _db_url: str) -> None:
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                product_id, warehouse_id = _seed_product_and_warehouse(conn)
                with pytest.raises(IntegrityError):
                    self._insert_txn(conn, product_id, warehouse_id, ordered_quantity=-1)
        finally:
            engine.dispose()

    def test_sales_order_id_fk_rejected(self, _db_url: str) -> None:
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                product_id, warehouse_id = _seed_product_and_warehouse(conn)
                with pytest.raises(IntegrityError):
                    self._insert_txn(conn, product_id, warehouse_id, sales_order_id=999999)
        finally:
            engine.dispose()

    def test_sales_order_item_id_fk_rejected(self, _db_url: str) -> None:
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                product_id, warehouse_id = _seed_product_and_warehouse(conn)
                with pytest.raises(IntegrityError):
                    self._insert_txn(conn, product_id, warehouse_id, sales_order_item_id=999999)
        finally:
            engine.dispose()

    def test_valid_signed_quantity_accepted(self, _db_url: str) -> None:
        """quantity 可为正（in）/负（out）/零盘点，均不设 CHECK，仅允许合法数量。"""
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                product_id, warehouse_id = _seed_product_and_warehouse(conn)
                self._insert_txn(
                    conn, product_id, warehouse_id, quantity=0, transaction_type="count"
                )
                self._insert_txn(conn, product_id, warehouse_id, quantity=5, transaction_type="in")
                self._insert_txn(
                    conn, product_id, warehouse_id, quantity=-5, transaction_type="out"
                )
                count = conn.execute(
                    text("SELECT COUNT(*) FROM inventory_transactions")
                ).scalar_one()
                assert count == 3
        finally:
            engine.dispose()


class TestAccountingSchemaStructure:
    """会计（chart_of_accounts / journal_entries / journal_entry_lines）与
    receivable_allocations 的 Alembic-head 结构断言（真实 SQLite 库）。"""

    @staticmethod
    def _head_up(_db_url: str) -> None:
        command.upgrade(_alembic_config(), "head")

    def test_chart_of_accounts_checks_exist(self, _db_url: str) -> None:
        self._head_up(_db_url)
        checks = _check_constraint_names(_db_url, "chart_of_accounts")
        assert {
            "ck_chart_of_accounts_type_in_account_types",
            "ck_chart_of_accounts_debit_credit",
        } <= checks

    def test_journal_entries_checks_exist(self, _db_url: str) -> None:
        self._head_up(_db_url)
        checks = _check_constraint_names(_db_url, "journal_entries")
        assert {
            "ck_journal_entries_posted_balanced",
            "ck_journal_entries_is_credit_note",
        } <= checks

    def test_journal_entry_lines_checks_exist(self, _db_url: str) -> None:
        self._head_up(_db_url)
        checks = _check_constraint_names(_db_url, "journal_entry_lines")
        assert {
            "ck_journal_entry_lines_nonnegative",
            "ck_journal_entry_lines_not_both_positive",
        } <= checks

    def test_receivable_allocations_checks_exist(self, _db_url: str) -> None:
        self._head_up(_db_url)
        checks = _check_constraint_names(_db_url, "receivable_allocations")
        assert {
            "ck_receivable_allocations_status_valid",
            "ck_receivable_allocations_amount_non_negative",
            "ck_receivable_allocations_allocated_amount_non_negative",
            "ck_receivable_allocations_allocated_le_amount",
        } <= checks

    def test_journal_entries_two_self_fks_exist(self, _db_url: str) -> None:
        self._head_up(_db_url)
        je_fks = _foreign_keys(_db_url, "journal_entries")
        actual = {
            (
                tuple(fk.get("constrained_columns") or []),
                fk.get("referred_table"),
                tuple(fk.get("referred_columns") or []),
            )
            for fk in je_fks
        }
        assert {
            (("reversed_of_id",), "journal_entries", ("id",)),
            (("credit_note_of_id",), "journal_entries", ("id",)),
        } <= actual

    def test_receivable_has_exactly_four_fk_structures(self, _db_url: str) -> None:
        self._head_up(_db_url)
        receivable_fks = _foreign_keys(_db_url, "receivable_allocations")
        actual = {
            (
                tuple(fk.get("constrained_columns") or []),
                fk.get("referred_table"),
                tuple(fk.get("referred_columns") or []),
            )
            for fk in receivable_fks
        }
        expected = {
            (("sales_order_id",), "sales_orders", ("id",)),
            (("journal_entry_id",), "journal_entries", ("id",)),
            (("line_id",), "journal_entry_lines", ("id",)),
            (("reversed_of_id",), "receivable_allocations", ("id",)),
        }
        assert len(receivable_fks) == 4
        assert actual == expected

    def test_required_accounting_and_receivable_indexes_exist(self, _db_url: str) -> None:
        self._head_up(_db_url)
        je_idx = {i["name"] for i in _indexes(_db_url, "journal_entries")}
        assert {
            "ix_journal_entries_reversed_of_id",
            "ix_journal_entries_credit_note_of_id",
        } <= je_idx
        jl_idx = {i["name"] for i in _indexes(_db_url, "journal_entry_lines")}
        assert {
            "ix_journal_entry_lines_entry_id",
            "ix_journal_entry_lines_account_id",
        } <= jl_idx
        ra_idx = {i["name"] for i in _indexes(_db_url, "receivable_allocations")}
        assert {
            "ix_receivable_allocations_sales_order_id",
            "ix_receivable_allocations_journal_entry_id",
            "ix_receivable_allocations_line_id",
            "ix_receivable_allocations_status",
            "ix_receivable_allocations_reference_id",
            "ix_receivable_allocations_reversed_of_id",
        } <= ra_idx


class TestJournalConstraintRejection:
    """会计 journal_entries / journal_entry_lines / chart_of_accounts
    DB 级约束拒绝与有效插入测试（SQLite Alembic head 真实库）。"""

    @staticmethod
    def _head_up(_db_url: str) -> None:
        command.upgrade(_alembic_config(), "head")

    @staticmethod
    def _insert_entry(
        conn,
        entry_no: str,
        status: str,
        debit: float,
        credit: float,
        is_credit_note: int = 0,
    ) -> int:
        return conn.execute(
            text(
                "INSERT INTO journal_entries (tenant_id, entry_no, status, "
                "is_credit_note, debit_total, credit_total) "
                "VALUES (1, :no, :status, :cn, :debit, :credit)"
            ),
            {
                "no": entry_no,
                "status": status,
                "cn": is_credit_note,
                "debit": debit,
                "credit": credit,
            },
        ).lastrowid

    def test_invalid_chart_account_type_rejected(self, _db_url: str) -> None:
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO chart_of_accounts (tenant_id, code, name, type, "
                            "debit_credit) VALUES (1, 'ACCT', 'A', 'bogus', 'debit')"
                        )
                    )
        finally:
            engine.dispose()

    def test_invalid_chart_of_accounts_debit_credit_rejected(self, _db_url: str) -> None:
        """chart_of_accounts.debit_credit 取值非法（非 debit/credit）→ CHECK 拒绝。"""
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO chart_of_accounts (tenant_id, code, name, type, "
                            "debit_credit) VALUES (1, 'ACCT', 'A', 'asset', 'bogus')"
                        )
                    )
        finally:
            engine.dispose()

    def test_unbalanced_posted_entry_rejected(self, _db_url: str) -> None:
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                with pytest.raises(IntegrityError):
                    self._insert_entry(conn, "JE-BAD", "posted", 100, 50)
        finally:
            engine.dispose()

    def test_is_credit_note_outside_01_rejected(self, _db_url: str) -> None:
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                with pytest.raises(IntegrityError):
                    self._insert_entry(conn, "JE-CN", "draft", 0, 0, is_credit_note=2)
        finally:
            engine.dispose()

    def test_missing_reversed_of_fk_target_rejected(self, _db_url: str) -> None:
        """reversed_of_id 指向不存在的凭证 → 自引用 FK 拒绝。"""
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO journal_entries (tenant_id, entry_no, status, "
                            "is_credit_note, reversed_of_id) "
                            "VALUES (1, 'JE-REV', 'draft', 0, 999999)"
                        )
                    )
        finally:
            engine.dispose()

    def test_missing_credit_note_of_fk_target_rejected(self, _db_url: str) -> None:
        """credit_note_of_id 指向不存在的凭证 → 自引用 FK 拒绝。"""
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO journal_entries (tenant_id, entry_no, status, "
                            "is_credit_note, credit_note_of_id) "
                            "VALUES (1, 'JE-CNOF', 'draft', 0, 999999)"
                        )
                    )
        finally:
            engine.dispose()

    def test_negative_debit_rejected(self, _db_url: str) -> None:
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                entry_id = self._insert_entry(conn, "JE-1", "draft", 0, 0)
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO journal_entry_lines (tenant_id, entry_id, debit, credit) "
                            "VALUES (1, :e, -1, 0)"
                        ),
                        {"e": entry_id},
                    )
        finally:
            engine.dispose()

    def test_negative_credit_rejected(self, _db_url: str) -> None:
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                entry_id = self._insert_entry(conn, "JE-1", "draft", 0, 0)
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO journal_entry_lines (tenant_id, entry_id, debit, credit) "
                            "VALUES (1, :e, 0, -1)"
                        ),
                        {"e": entry_id},
                    )
        finally:
            engine.dispose()

    def test_both_debit_and_credit_positive_rejected(self, _db_url: str) -> None:
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                entry_id = self._insert_entry(conn, "JE-1", "draft", 0, 0)
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO journal_entry_lines (tenant_id, entry_id, debit, credit) "
                            "VALUES (1, :e, 10, 10)"
                        ),
                        {"e": entry_id},
                    )
        finally:
            engine.dispose()

    def test_balanced_posted_entry_accepted(self, _db_url: str) -> None:
        """借贷平衡的 posted 分录落库成功。"""
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                entry_id = self._insert_entry(conn, "JE-BAL", "posted", 100, 100)
                assert entry_id is not None
                count = conn.execute(
                    text("SELECT COUNT(*) FROM journal_entries WHERE status='posted'")
                ).scalar_one()
                assert count == 1
        finally:
            engine.dispose()

    def test_one_sided_journal_line_accepted(self, _db_url: str) -> None:
        """单边（仅借或仅贷）分录行合法落库。"""
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                entry_id = self._insert_entry(conn, "JE-1", "draft", 0, 0)
                conn.execute(
                    text(
                        "INSERT INTO journal_entry_lines (tenant_id, entry_id, debit, credit) "
                        "VALUES (1, :e, 100, 0)"
                    ),
                    {"e": entry_id},
                )
                conn.execute(
                    text(
                        "INSERT INTO journal_entry_lines (tenant_id, entry_id, debit, credit) "
                        "VALUES (1, :e, 0, 100)"
                    ),
                    {"e": entry_id},
                )
                count = conn.execute(
                    text("SELECT COUNT(*) FROM journal_entry_lines WHERE entry_id = :e"),
                    {"e": entry_id},
                ).scalar_one()
                assert count == 2
        finally:
            engine.dispose()


class TestReceivableAllocationConstraintRejection:
    """receivable_allocations DB 级约束拒绝与有效插入测试（SQLite Alembic head 真实库）。"""

    @staticmethod
    def _head_up(_db_url: str) -> None:
        command.upgrade(_alembic_config(), "head")

    @staticmethod
    def _insert(conn, **overrides) -> int:
        base = {
            "tenant_id": 1,
            "status": "unpaid",
            "amount": 100,
            "allocated_amount": 50,
        }
        base.update(overrides)
        col_names = ", ".join(base)
        placeholders = ", ".join(f":{k}" for k in base)
        return conn.execute(
            text(f"INSERT INTO receivable_allocations ({col_names}) VALUES ({placeholders})"),
            base,
        ).lastrowid

    def test_invalid_status_rejected(self, _db_url: str) -> None:
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                with pytest.raises(IntegrityError):
                    self._insert(conn, status="bogus")
        finally:
            engine.dispose()

    def test_negative_amount_rejected(self, _db_url: str) -> None:
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                with pytest.raises(IntegrityError):
                    self._insert(conn, amount=-1)
        finally:
            engine.dispose()

    def test_negative_allocated_amount_rejected(self, _db_url: str) -> None:
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                with pytest.raises(IntegrityError):
                    self._insert(conn, allocated_amount=-1)
        finally:
            engine.dispose()

    def test_allocated_exceeds_amount_rejected(self, _db_url: str) -> None:
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                with pytest.raises(IntegrityError):
                    self._insert(conn, amount=100, allocated_amount=150)
        finally:
            engine.dispose()

    def test_missing_sales_order_fk_target_rejected(self, _db_url: str) -> None:
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                with pytest.raises(IntegrityError):
                    self._insert(conn, sales_order_id=999999)
        finally:
            engine.dispose()

    def test_missing_journal_entry_fk_target_rejected(self, _db_url: str) -> None:
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                with pytest.raises(IntegrityError):
                    self._insert(conn, journal_entry_id=999999)
        finally:
            engine.dispose()

    def test_missing_line_fk_target_rejected(self, _db_url: str) -> None:
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                with pytest.raises(IntegrityError):
                    self._insert(conn, line_id=999999)
        finally:
            engine.dispose()

    def test_missing_reversed_of_fk_target_rejected(self, _db_url: str) -> None:
        """reversed_of_id 指向不存在的 allocation → 自引用 FK 拒绝（需 PRAGMA foreign_keys=ON）。"""
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                with pytest.raises(IntegrityError):
                    self._insert(conn, reversed_of_id=999999)
        finally:
            engine.dispose()

    def test_valid_allocation_accepted(self, _db_url: str) -> None:
        """合法分配（金额 100、已分配 50、未超过 amount）落库成功。"""
        self._head_up(_db_url)
        engine = _fk_engine(_db_url)
        try:
            with engine.connect() as conn:
                allocation_id = self._insert(conn)
                assert allocation_id is not None
                count = conn.execute(
                    text("SELECT COUNT(*) FROM receivable_allocations")
                ).scalar_one()
                assert count == 1
        finally:
            engine.dispose()
