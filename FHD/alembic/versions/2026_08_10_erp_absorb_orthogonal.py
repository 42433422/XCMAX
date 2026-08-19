"""ODOO-W1-01 ERP 正交 schema 唯一 Alembic 迁移。

- 建表（若缺失）：sales_orders / sales_order_items / chart_of_accounts /
  journal_entries / journal_entry_lines / products / inventory_transactions /
  receivable_allocations。
- 改既有表：补正交维度字段 + 租户复合唯一约束 + DB 级借贷平衡约束 + UOM/补货字段。
- 存量 backfill：由旧线性 ``status`` 映射出 ``state / invoice_status / payment_state``。

SQLite 改动用 ``op.batch_alter_table(recreate="auto")``；forward upgrade 保留全部既有数据。

Revision ID: 2026_08_10_erp_absorb_orthogonal
Revises: 2026_07_27_etl_folder_batches
Create Date: 2026-08-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_08_10_erp_absorb_orthogonal"
down_revision: str | Sequence[str] | None = "2026_07_27_etl_folder_batches"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NUM4 = sa.Numeric(18, 4)
_NUM6 = sa.Numeric(18, 6)
_NUM2 = sa.Numeric(18, 2)


def _table_exists(bind, name: str) -> bool:
    return name in sa.inspect(bind).get_table_names()


def _columns(bind, name: str) -> set[str]:
    if not _table_exists(bind, name):
        return set()
    return {str(c["name"]) for c in sa.inspect(bind).get_columns(name)}


def _indexes(bind, name: str) -> dict[str, dict]:
    if not _table_exists(bind, name):
        return {}
    return {str(i["name"]): i for i in sa.inspect(bind).get_indexes(name)}


def _unique_index_on(bind, table: str, col: str) -> str | None:
    """返回对 ``table.col`` 施加单列唯一的独立索引名。

    PostgreSQL 会同时将 UNIQUE constraint 反射为 index；这类条目必须
    通过 ``drop_constraint`` 删除，不能当成独立索引 ``drop_index``。
    """
    for name, idx in _indexes(bind, table).items():
        cols = list(idx.get("column_names") or [])
        if cols == [col] and idx.get("unique") and not idx.get("duplicates_constraint"):
            return name
    return None


def _add_column_if_missing(bind, table: str, col: str, column) -> None:
    cols = _columns(bind, table)
    if col not in cols:
        with op.batch_alter_table(table, recreate="auto") as batch_op:
            batch_op.add_column(column)


def _ensure_tenant_unique(bind, table: str, col: str, constraint_name: str) -> None:
    """将单列唯一改为 ``(tenant_id, col)`` 复合唯一。"""
    constraints = sa.inspect(bind).get_unique_constraints(table)
    for constraint in constraints:
        name = constraint.get("name")
        if name and list(constraint.get("column_names") or []) == [col]:
            with op.batch_alter_table(table, recreate="auto") as batch_op:
                batch_op.drop_constraint(str(name), type_="unique")

    old = _unique_index_on(bind, table, col)
    if old:
        with op.batch_alter_table(table, recreate="auto") as batch_op:
            batch_op.drop_index(old)
    constraint_names = {str(c["name"]) for c in sa.inspect(bind).get_unique_constraints(table)}
    if constraint_name not in constraint_names:
        with op.batch_alter_table(table, recreate="auto") as batch_op:
            batch_op.create_unique_constraint(constraint_name, ["tenant_id", col])


def _ensure_check_constraint(bind, table: str, name: str, check: str) -> None:
    """按名幂等创建 DB 级 CHECK 约束（存在则跳过）。"""
    names = {str(c["name"]) for c in sa.inspect(bind).get_check_constraints(table)}
    if name not in names:
        with op.batch_alter_table(table, recreate="auto") as batch_op:
            batch_op.create_check_constraint(name, check)


def _ensure_foreign_key(
    bind, table: str, name: str, referred: str, local_cols: list[str], remote_cols: list[str]
) -> None:
    """按名/结构幂等创建 FK（结构缺失时才创建），SQLite/PostgreSQL 均通过 recreate 支持。

    SQLite 不持久化 FK 约束名，反射出的 ``name`` 常为 ``None``，仅按名判断会
    误判"不存在"从而重复建同名 FK。因此：当已存在一个 constrained columns、
    referred table、referred columns 均与目标一致的 FK 时视为已存在并跳过；
    仅当结构缺失时才创建带 ``name`` 的 FK。
    """
    for fk in sa.inspect(bind).get_foreign_keys(table):
        if (
            list(fk.get("constrained_columns") or []) == local_cols
            and fk.get("referred_table") == referred
            and list(fk.get("referred_columns") or []) == remote_cols
        ):
            return
    with op.batch_alter_table(table, recreate="auto") as batch_op:
        batch_op.create_foreign_key(name, referred, local_cols, remote_cols)


def _ensure_index(bind, table: str, name: str, cols: list[str]) -> None:
    """按名幂等创建索引（不存在则创建）。"""
    if name not in _indexes(bind, table):
        with op.batch_alter_table(table, recreate="auto") as batch_op:
            batch_op.create_index(name, cols)


# --------------------------------------------------------------------------- #
# 建表（仅当表缺失时）
# --------------------------------------------------------------------------- #
def _create_sales_orders_if_missing(bind) -> None:
    if _table_exists(bind, "sales_orders"):
        return
    op.create_table(
        "sales_orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("order_no", sa.String(50), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("customer_name", sa.String(200), nullable=True),
        sa.Column("state", sa.String(20), nullable=False, server_default="quote"),
        sa.Column("status", sa.String(20), nullable=False, server_default="quote"),
        sa.Column("invoice_status", sa.String(20), nullable=False, server_default="not_invoiced"),
        sa.Column("payment_state", sa.String(20), nullable=False, server_default="unpaid"),
        sa.Column("quote_date", sa.Date(), nullable=True),
        sa.Column("sent_date", sa.Date(), nullable=True),
        sa.Column("confirm_date", sa.Date(), nullable=True),
        sa.Column("cancel_date", sa.Date(), nullable=True),
        sa.Column("total_amount", _NUM2, nullable=True, server_default="0"),
        sa.Column("paid_amount", _NUM2, nullable=True, server_default="0"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="CNY"),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("backorder_of_id", sa.Integer(), nullable=True),
        sa.Column("return_of_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["backorder_of_id"],
            ["sales_orders.id"],
            name="fk_sales_orders_backorder_of_id_sales_orders",
        ),
        sa.ForeignKeyConstraint(
            ["return_of_id"],
            ["sales_orders.id"],
            name="fk_sales_orders_return_of_id_sales_orders",
        ),
        sa.UniqueConstraint("tenant_id", "order_no", name="uq_sales_orders_tenant_order_no"),
        sa.CheckConstraint(
            "state IN ('draft','quote','sent','confirmed','cancel')",
            name="ck_sales_orders_state_valid",
        ),
        sa.CheckConstraint(
            "invoice_status IN ('not_invoiced','invoiced','invoiced_partial','credit_note')",
            name="ck_sales_orders_invoice_status_valid",
        ),
        sa.CheckConstraint(
            "payment_state IN ('unpaid','partial','paid','refunded')",
            name="ck_sales_orders_payment_state_valid",
        ),
        sa.CheckConstraint(
            "COALESCE(total_amount, 0) >= 0",
            name="ck_sales_orders_total_amount_non_negative",
        ),
        sa.CheckConstraint(
            "COALESCE(paid_amount, 0) >= 0",
            name="ck_sales_orders_paid_amount_non_negative",
        ),
    )


def _create_sales_order_items_if_missing(bind) -> None:
    if _table_exists(bind, "sales_order_items"):
        return
    op.create_table(
        "sales_order_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), nullable=True, index=True),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("product_name", sa.String(200), nullable=True),
        sa.Column("specification", sa.String(200), nullable=True),
        sa.Column("quantity", _NUM4, nullable=False, server_default="0"),
        sa.Column("unit", sa.String(20), nullable=False, server_default="个"),
        sa.Column("unit_price", _NUM4, nullable=True, server_default="0"),
        sa.Column("amount", _NUM2, nullable=True, server_default="0"),
        sa.Column("ordered_quantity", _NUM4, nullable=True, server_default="0"),
        sa.Column("reserved_quantity", _NUM4, nullable=True, server_default="0"),
        sa.Column("delivered_quantity", _NUM4, nullable=True, server_default="0"),
        sa.Column("returned_quantity", _NUM4, nullable=True, server_default="0"),
        sa.Column("invoiced_quantity", _NUM4, nullable=True, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["sales_orders.id"],
            name="fk_sales_order_items_order_id_sales_orders",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_sales_order_items_product_id_products",
        ),
        sa.CheckConstraint(
            "COALESCE(quantity, 0) >= 0",
            name="ck_sales_order_items_quantity_non_negative",
        ),
        sa.CheckConstraint(
            "COALESCE(unit_price, 0) >= 0",
            name="ck_sales_order_items_unit_price_non_negative",
        ),
        sa.CheckConstraint(
            "COALESCE(amount, 0) >= 0",
            name="ck_sales_order_items_amount_non_negative",
        ),
        sa.CheckConstraint(
            "COALESCE(ordered_quantity, 0) >= 0",
            name="ck_sales_order_items_ordered_non_negative",
        ),
        sa.CheckConstraint(
            "COALESCE(reserved_quantity, 0) >= 0",
            name="ck_sales_order_items_reserved_non_negative",
        ),
        sa.CheckConstraint(
            "COALESCE(delivered_quantity, 0) >= 0",
            name="ck_sales_order_items_delivered_non_negative",
        ),
        sa.CheckConstraint(
            "COALESCE(returned_quantity, 0) >= 0",
            name="ck_sales_order_items_returned_non_negative",
        ),
        sa.CheckConstraint(
            "COALESCE(invoiced_quantity, 0) >= 0",
            name="ck_sales_order_items_invoiced_non_negative",
        ),
        sa.CheckConstraint(
            "COALESCE(reserved_quantity, 0) <= COALESCE(ordered_quantity, 0)",
            name="ck_sales_order_items_reserved_le_ordered",
        ),
        sa.CheckConstraint(
            "COALESCE(delivered_quantity, 0) <= COALESCE(ordered_quantity, 0)",
            name="ck_sales_order_items_delivered_le_ordered",
        ),
        sa.CheckConstraint(
            "COALESCE(returned_quantity, 0) <= COALESCE(delivered_quantity, 0)",
            name="ck_sales_order_items_returned_le_delivered",
        ),
    )


def _create_chart_of_accounts_if_missing(bind) -> None:
    if _table_exists(bind, "chart_of_accounts"):
        return
    op.create_table(
        "chart_of_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("type", sa.String(20), nullable=False, server_default="asset"),
        sa.Column("debit_credit", sa.String(10), nullable=False, server_default="debit"),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_chart_of_accounts_tenant_code"),
        sa.CheckConstraint(
            "type IN ('asset','equity','expense','liability','revenue')",
            name="ck_chart_of_accounts_type_in_account_types",
        ),
        sa.CheckConstraint(
            "debit_credit IN ('debit','credit')",
            name="ck_chart_of_accounts_debit_credit",
        ),
    )


def _create_journal_entries_if_missing(bind) -> None:
    if _table_exists(bind, "journal_entries"):
        return
    op.create_table(
        "journal_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("entry_no", sa.String(50), nullable=False),
        sa.Column("journal_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("reference_type", sa.String(64), nullable=True),
        sa.Column("reference_id", sa.Integer(), nullable=True),
        sa.Column("debit_total", _NUM2, nullable=True, server_default="0"),
        sa.Column("credit_total", _NUM2, nullable=True, server_default="0"),
        sa.Column("reversed_of_id", sa.Integer(), nullable=True),
        sa.Column("reversed_at", sa.DateTime(), nullable=True),
        sa.Column("credit_note_of_id", sa.Integer(), nullable=True),
        sa.Column("is_credit_note", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["reversed_of_id"],
            ["journal_entries.id"],
            name="fk_journal_entries_reversed_of_id_journal_entries",
        ),
        sa.ForeignKeyConstraint(
            ["credit_note_of_id"],
            ["journal_entries.id"],
            name="fk_journal_entries_credit_note_of_id_journal_entries",
        ),
        sa.UniqueConstraint("tenant_id", "entry_no", name="uq_journal_entries_tenant_entry_no"),
        sa.CheckConstraint(
            "status != 'posted' OR ABS(COALESCE(debit_total,0) - COALESCE(credit_total,0)) < 0.01",
            name="ck_journal_entries_posted_balanced",
        ),
        sa.CheckConstraint(
            "is_credit_note IN (0,1)",
            name="ck_journal_entries_is_credit_note",
        ),
    )


def _create_journal_entry_lines_if_missing(bind) -> None:
    if _table_exists(bind, "journal_entry_lines"):
        return
    op.create_table(
        "journal_entry_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), nullable=True, index=True),
        sa.Column("entry_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("account_code", sa.String(50), nullable=True),
        sa.Column("account_name", sa.String(200), nullable=True),
        sa.Column("debit", _NUM2, nullable=True, server_default="0"),
        sa.Column("credit", _NUM2, nullable=True, server_default="0"),
        sa.Column("partner_id", sa.Integer(), nullable=True),
        sa.Column("partner_name", sa.String(200), nullable=True),
        sa.Column("reference", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["entry_id"],
            ["journal_entries.id"],
            name="fk_journal_entry_lines_entry_id_journal_entries",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["chart_of_accounts.id"],
            name="fk_journal_entry_lines_account_id_chart_of_accounts",
        ),
        sa.CheckConstraint(
            "COALESCE(debit,0) >= 0 AND COALESCE(credit,0) >= 0",
            name="ck_journal_entry_lines_nonnegative",
        ),
        sa.CheckConstraint(
            "NOT (COALESCE(debit,0) > 0 AND COALESCE(credit,0) > 0)",
            name="ck_journal_entry_lines_not_both_positive",
        ),
    )


def _create_products_if_missing(bind) -> None:
    if _table_exists(bind, "products"):
        return
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("model_number", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("specification", sa.String(), nullable=True),
        sa.Column("price", sa.Numeric(10, 2), nullable=True, server_default="0.0"),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("brand", sa.String(), nullable=True),
        sa.Column("unit", sa.String(), nullable=False, server_default="个"),
        sa.Column("base_uom_id", sa.Integer(), nullable=True, index=True),
        sa.Column("uom_category", sa.String(), nullable=True, server_default="unit"),
        sa.Column("uom_factor", _NUM6, nullable=True, server_default="1"),
        sa.Column("min_stock", _NUM4, nullable=True, server_default="0"),
        sa.Column("max_stock", _NUM4, nullable=True, server_default="0"),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(
            ["base_uom_id"],
            ["uom_units.id"],
            name="fk_products_base_uom_id_uom_units",
        ),
        sa.CheckConstraint("COALESCE(uom_factor, 1) > 0", name="ck_products_uom_factor_positive"),
        sa.CheckConstraint("COALESCE(min_stock, 0) >= 0", name="ck_products_min_stock_nonnegative"),
        sa.CheckConstraint("COALESCE(max_stock, 0) >= 0", name="ck_products_max_stock_nonnegative"),
        sa.CheckConstraint(
            "COALESCE(min_stock, 0) <= COALESCE(max_stock, 0)",
            name="ck_products_min_stock_le_max_stock",
        ),
    )


def _create_inventory_transactions_if_missing(bind) -> None:
    if _table_exists(bind, "inventory_transactions"):
        return
    op.create_table(
        "inventory_transactions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), nullable=True, index=True),
        sa.Column("ledger_id", sa.Integer(), nullable=True),
        sa.Column("transaction_type", sa.String(20), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=True),
        sa.Column("batch_no", sa.String(50), nullable=True),
        sa.Column("quantity", _NUM4, nullable=False),
        sa.Column("before_quantity", _NUM4, nullable=True),
        sa.Column("after_quantity", _NUM4, nullable=True),
        sa.Column("unit_price", _NUM4, nullable=True),
        sa.Column("total_amount", _NUM2, nullable=True),
        sa.Column("reference_type", sa.String(50), nullable=True),
        sa.Column("reference_id", sa.Integer(), nullable=True),
        sa.Column("ordered_quantity", _NUM4, nullable=True, server_default="0"),
        sa.Column("delivered_quantity", _NUM4, nullable=True, server_default="0"),
        sa.Column("sales_order_id", sa.Integer(), nullable=True),
        sa.Column("sales_order_item_id", sa.Integer(), nullable=True),
        sa.Column("transaction_date", sa.DateTime(), nullable=False),
        sa.Column("operator", sa.String(50), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def _create_receivable_allocations_if_missing(bind) -> None:
    if _table_exists(bind, "receivable_allocations"):
        return
    op.create_table(
        "receivable_allocations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("sales_order_id", sa.Integer(), nullable=True),
        sa.Column("journal_entry_id", sa.Integer(), nullable=True),
        sa.Column("line_id", sa.Integer(), nullable=True),
        sa.Column("amount", _NUM2, nullable=True, server_default="0"),
        sa.Column("allocated_amount", _NUM2, nullable=True, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="unpaid"),
        sa.Column("reference_type", sa.String(64), nullable=True),
        sa.Column("reference_id", sa.Integer(), nullable=True),
        sa.Column("reversed_of_id", sa.Integer(), nullable=True),
        sa.Column("allocated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["sales_order_id"],
            ["sales_orders.id"],
            name="fk_receivable_allocations_sales_order_id_sales_orders",
        ),
        sa.ForeignKeyConstraint(
            ["journal_entry_id"],
            ["journal_entries.id"],
            name="fk_receivable_allocations_journal_entry_id_journal_entries",
        ),
        sa.ForeignKeyConstraint(
            ["line_id"],
            ["journal_entry_lines.id"],
            name="fk_receivable_allocations_line_id_journal_entry_lines",
        ),
        sa.ForeignKeyConstraint(
            ["reversed_of_id"],
            ["receivable_allocations.id"],
            name="fk_receivable_allocations_reversed_of_id",
        ),
        sa.CheckConstraint(
            "status IN ('unpaid', 'partial', 'paid', 'refunded')",
            name="ck_receivable_allocations_status_valid",
        ),
        sa.CheckConstraint(
            "COALESCE(amount, 0) >= 0",
            name="ck_receivable_allocations_amount_non_negative",
        ),
        sa.CheckConstraint(
            "COALESCE(allocated_amount, 0) >= 0",
            name="ck_receivable_allocations_allocated_amount_non_negative",
        ),
        sa.CheckConstraint(
            "COALESCE(allocated_amount, 0) <= COALESCE(amount, 0)",
            name="ck_receivable_allocations_allocated_le_amount",
        ),
        sa.Index("ix_receivable_allocations_sales_order_id", "sales_order_id"),
        sa.Index("ix_receivable_allocations_journal_entry_id", "journal_entry_id"),
        sa.Index("ix_receivable_allocations_line_id", "line_id"),
        sa.Index("ix_receivable_allocations_status", "status"),
        sa.Index("ix_receivable_allocations_reference_id", "reference_id"),
        sa.Index("ix_receivable_allocations_reversed_of_id", "reversed_of_id"),
    )


def _create_uom_categories_if_missing(bind) -> None:
    if _table_exists(bind, "uom_categories"):
        return
    op.create_table(
        "uom_categories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_uom_categories_tenant_code"),
    )


def _create_uom_units_if_missing(bind) -> None:
    if _table_exists(bind, "uom_units"):
        return
    op.create_table(
        "uom_units",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("category_id", sa.Integer(), nullable=False, index=True),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("factor", _NUM6, nullable=False),
        sa.Column("is_reference", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["uom_categories.id"],
            name="fk_uom_units_category_id_uom_categories",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "category_id",
            "code",
            name="uq_uom_units_tenant_category_code",
        ),
        sa.CheckConstraint("factor > 0", name="ck_uom_units_factor_positive"),
        sa.CheckConstraint("is_reference IN (0, 1)", name="ck_uom_units_is_reference_bool"),
    )


# --------------------------------------------------------------------------- #
# 改既有表
# --------------------------------------------------------------------------- #
def _alter_sales_orders(bind) -> None:
    if not _table_exists(bind, "sales_orders"):
        return
    for col, column in [
        ("state", sa.Column("state", sa.String(20), nullable=False, server_default="quote")),
        (
            "invoice_status",
            sa.Column(
                "invoice_status", sa.String(20), nullable=False, server_default="not_invoiced"
            ),
        ),
        (
            "payment_state",
            sa.Column("payment_state", sa.String(20), nullable=False, server_default="unpaid"),
        ),
        ("sent_date", sa.Column("sent_date", sa.Date(), nullable=True)),
        ("cancel_date", sa.Column("cancel_date", sa.Date(), nullable=True)),
        ("backorder_of_id", sa.Column("backorder_of_id", sa.Integer(), nullable=True)),
        ("return_of_id", sa.Column("return_of_id", sa.Integer(), nullable=True)),
    ]:
        _add_column_if_missing(bind, "sales_orders", col, column)
    _ensure_tenant_unique(bind, "sales_orders", "order_no", "uq_sales_orders_tenant_order_no")
    _ensure_foreign_key(
        bind,
        "sales_orders",
        "fk_sales_orders_backorder_of_id_sales_orders",
        "sales_orders",
        ["backorder_of_id"],
        ["id"],
    )
    _ensure_foreign_key(
        bind,
        "sales_orders",
        "fk_sales_orders_return_of_id_sales_orders",
        "sales_orders",
        ["return_of_id"],
        ["id"],
    )
    for name, check in [
        (
            "ck_sales_orders_state_valid",
            "state IN ('draft','quote','sent','confirmed','cancel')",
        ),
        (
            "ck_sales_orders_invoice_status_valid",
            "invoice_status IN ('not_invoiced','invoiced','invoiced_partial','credit_note')",
        ),
        (
            "ck_sales_orders_payment_state_valid",
            "payment_state IN ('unpaid','partial','paid','refunded')",
        ),
        ("ck_sales_orders_total_amount_non_negative", "COALESCE(total_amount, 0) >= 0"),
        ("ck_sales_orders_paid_amount_non_negative", "COALESCE(paid_amount, 0) >= 0"),
    ]:
        _ensure_check_constraint(bind, "sales_orders", name, check)


def _alter_sales_order_items(bind) -> None:
    if not _table_exists(bind, "sales_order_items"):
        return
    for col, column in [
        (
            "ordered_quantity",
            sa.Column("ordered_quantity", _NUM4, nullable=True, server_default="0"),
        ),
        (
            "reserved_quantity",
            sa.Column("reserved_quantity", _NUM4, nullable=True, server_default="0"),
        ),
        (
            "returned_quantity",
            sa.Column("returned_quantity", _NUM4, nullable=True, server_default="0"),
        ),
    ]:
        _add_column_if_missing(bind, "sales_order_items", col, column)
    # 在建相对数量 CHECK（reserved/delivered/returned <= ordered）前，将
    # ordered_quantity 垫高到不小于既有 quantity/reserved/delivered/returned 的最大值，
    # 保证存量行不被丢弃且能通过约束。
    _backfill_sales_order_items_quantities(bind)
    _ensure_foreign_key(
        bind,
        "sales_order_items",
        "fk_sales_order_items_order_id_sales_orders",
        "sales_orders",
        ["order_id"],
        ["id"],
    )
    _ensure_foreign_key(
        bind,
        "sales_order_items",
        "fk_sales_order_items_product_id_products",
        "products",
        ["product_id"],
        ["id"],
    )
    for name, check in [
        ("ck_sales_order_items_quantity_non_negative", "COALESCE(quantity, 0) >= 0"),
        ("ck_sales_order_items_unit_price_non_negative", "COALESCE(unit_price, 0) >= 0"),
        ("ck_sales_order_items_amount_non_negative", "COALESCE(amount, 0) >= 0"),
        (
            "ck_sales_order_items_ordered_non_negative",
            "COALESCE(ordered_quantity, 0) >= 0",
        ),
        (
            "ck_sales_order_items_reserved_non_negative",
            "COALESCE(reserved_quantity, 0) >= 0",
        ),
        (
            "ck_sales_order_items_delivered_non_negative",
            "COALESCE(delivered_quantity, 0) >= 0",
        ),
        (
            "ck_sales_order_items_returned_non_negative",
            "COALESCE(returned_quantity, 0) >= 0",
        ),
        (
            "ck_sales_order_items_invoiced_non_negative",
            "COALESCE(invoiced_quantity, 0) >= 0",
        ),
        (
            "ck_sales_order_items_reserved_le_ordered",
            "COALESCE(reserved_quantity, 0) <= COALESCE(ordered_quantity, 0)",
        ),
        (
            "ck_sales_order_items_delivered_le_ordered",
            "COALESCE(delivered_quantity, 0) <= COALESCE(ordered_quantity, 0)",
        ),
        (
            "ck_sales_order_items_returned_le_delivered",
            "COALESCE(returned_quantity, 0) <= COALESCE(delivered_quantity, 0)",
        ),
    ]:
        _ensure_check_constraint(bind, "sales_order_items", name, check)


def _backfill_sales_order_items_quantities(bind) -> None:
    """将 ordered_quantity 垫高到不小于既有 quantity/reserved/delivered/returned 的最大值。

    仅当当前 ordered_quantity 小于该最大值时才更新，避免相对数量 CHECK 在存量数据上失败。
    PostgreSQL 与 SQLite 分别使用各自的 GREATEST/MAX 标量函数。
    """
    cols = _columns(bind, "sales_order_items")
    if "ordered_quantity" not in cols:
        return
    values = (
        "COALESCE(quantity,0),COALESCE(reserved_quantity,0),"
        "COALESCE(delivered_quantity,0),COALESCE(returned_quantity,0)"
    )
    if bind.dialect.name == "postgresql":
        greatest = f"GREATEST({values})"
    else:
        greatest = f"MAX({values})"
    bind.execute(
        sa.text(
            f"UPDATE sales_order_items SET ordered_quantity={greatest} "
            f"WHERE COALESCE(ordered_quantity,0) < {greatest}"
        )
    )


def _alter_chart_of_accounts(bind) -> None:
    if not _table_exists(bind, "chart_of_accounts"):
        return
    _ensure_tenant_unique(bind, "chart_of_accounts", "code", "uq_chart_of_accounts_tenant_code")
    for name, check in [
        (
            "ck_chart_of_accounts_type_in_account_types",
            "type IN ('asset','equity','expense','liability','revenue')",
        ),
        ("ck_chart_of_accounts_debit_credit", "debit_credit IN ('debit','credit')"),
    ]:
        _ensure_check_constraint(bind, "chart_of_accounts", name, check)


def _alter_journal_entries(bind) -> None:
    if not _table_exists(bind, "journal_entries"):
        return
    for col, column in [
        ("reversed_of_id", sa.Column("reversed_of_id", sa.Integer(), nullable=True)),
        ("credit_note_of_id", sa.Column("credit_note_of_id", sa.Integer(), nullable=True)),
        (
            "is_credit_note",
            sa.Column("is_credit_note", sa.Integer(), nullable=False, server_default="0"),
        ),
    ]:
        _add_column_if_missing(bind, "journal_entries", col, column)
    _ensure_tenant_unique(bind, "journal_entries", "entry_no", "uq_journal_entries_tenant_entry_no")
    _ensure_foreign_key(
        bind,
        "journal_entries",
        "fk_journal_entries_reversed_of_id_journal_entries",
        "journal_entries",
        ["reversed_of_id"],
        ["id"],
    )
    _ensure_foreign_key(
        bind,
        "journal_entries",
        "fk_journal_entries_credit_note_of_id_journal_entries",
        "journal_entries",
        ["credit_note_of_id"],
        ["id"],
    )
    # 与 ORM ``index=True`` 生成的索引名一致的履行/关联索引
    _ensure_index(bind, "journal_entries", "ix_journal_entries_reversed_of_id", ["reversed_of_id"])
    _ensure_index(
        bind, "journal_entries", "ix_journal_entries_credit_note_of_id", ["credit_note_of_id"]
    )
    for name, check in [
        (
            "ck_journal_entries_posted_balanced",
            "status != 'posted' OR ABS(COALESCE(debit_total,0) - COALESCE(credit_total,0)) < 0.01",
        ),
        ("ck_journal_entries_is_credit_note", "is_credit_note IN (0,1)"),
    ]:
        _ensure_check_constraint(bind, "journal_entries", name, check)


def _alter_journal_entry_lines(bind) -> None:
    if not _table_exists(bind, "journal_entry_lines"):
        return
    _ensure_foreign_key(
        bind,
        "journal_entry_lines",
        "fk_journal_entry_lines_entry_id_journal_entries",
        "journal_entries",
        ["entry_id"],
        ["id"],
    )
    _ensure_foreign_key(
        bind,
        "journal_entry_lines",
        "fk_journal_entry_lines_account_id_chart_of_accounts",
        "chart_of_accounts",
        ["account_id"],
        ["id"],
    )
    # 与 ORM ``index=True`` 生成的索引名一致的关联索引
    _ensure_index(bind, "journal_entry_lines", "ix_journal_entry_lines_entry_id", ["entry_id"])
    _ensure_index(bind, "journal_entry_lines", "ix_journal_entry_lines_account_id", ["account_id"])
    for name, check in [
        (
            "ck_journal_entry_lines_nonnegative",
            "COALESCE(debit,0) >= 0 AND COALESCE(credit,0) >= 0",
        ),
        (
            "ck_journal_entry_lines_not_both_positive",
            "NOT (COALESCE(debit,0) > 0 AND COALESCE(credit,0) > 0)",
        ),
    ]:
        _ensure_check_constraint(bind, "journal_entry_lines", name, check)


def _alter_products(bind) -> None:
    if not _table_exists(bind, "products"):
        return
    for col, column in [
        ("base_uom_id", sa.Column("base_uom_id", sa.Integer(), nullable=True)),
        (
            "uom_category",
            sa.Column("uom_category", sa.String(), nullable=True, server_default="unit"),
        ),
        ("uom_factor", sa.Column("uom_factor", _NUM6, nullable=True, server_default="1")),
        ("min_stock", sa.Column("min_stock", _NUM4, nullable=True, server_default="0")),
        ("max_stock", sa.Column("max_stock", _NUM4, nullable=True, server_default="0")),
    ]:
        _add_column_if_missing(bind, "products", col, column)
    _ensure_foreign_key(
        bind,
        "products",
        "fk_products_base_uom_id_uom_units",
        "uom_units",
        ["base_uom_id"],
        ["id"],
    )
    _ensure_index(bind, "products", "ix_products_base_uom_id", ["base_uom_id"])
    for name, check in [
        ("ck_products_uom_factor_positive", "COALESCE(uom_factor, 1) > 0"),
        ("ck_products_min_stock_nonnegative", "COALESCE(min_stock, 0) >= 0"),
        ("ck_products_max_stock_nonnegative", "COALESCE(max_stock, 0) >= 0"),
        (
            "ck_products_min_stock_le_max_stock",
            "COALESCE(min_stock, 0) <= COALESCE(max_stock, 0)",
        ),
    ]:
        _ensure_check_constraint(bind, "products", name, check)


def _alter_inventory_transactions(bind) -> None:
    if not _table_exists(bind, "inventory_transactions"):
        return
    for col, column in [
        (
            "ordered_quantity",
            sa.Column("ordered_quantity", _NUM4, nullable=True, server_default="0"),
        ),
        (
            "delivered_quantity",
            sa.Column("delivered_quantity", _NUM4, nullable=True, server_default="0"),
        ),
        ("sales_order_id", sa.Column("sales_order_id", sa.Integer(), nullable=True)),
        ("sales_order_item_id", sa.Column("sales_order_item_id", sa.Integer(), nullable=True)),
    ]:
        _add_column_if_missing(bind, "inventory_transactions", col, column)
    # sales_order_id → sales_orders.id、sales_order_item_id → sales_order_items.id 外键
    _ensure_foreign_key(
        bind,
        "inventory_transactions",
        "fk_inventory_transactions_sales_order_id_sales_orders",
        "sales_orders",
        ["sales_order_id"],
        ["id"],
    )
    _ensure_foreign_key(
        bind,
        "inventory_transactions",
        "fk_inventory_transactions_sales_order_item_id_sales_order_items",
        "sales_order_items",
        ["sales_order_item_id"],
        ["id"],
    )
    # 履行维度索引（与 ORM ``index=True`` 生成的索引名一致）
    _ensure_index(
        bind,
        "inventory_transactions",
        "ix_inventory_transactions_sales_order_id",
        ["sales_order_id"],
    )
    _ensure_index(
        bind,
        "inventory_transactions",
        "ix_inventory_transactions_sales_order_item_id",
        ["sales_order_item_id"],
    )
    # 履行维度 DB 级 CHECK：ordered/delivered 非负，且 delivered 不超过 ordered
    for name, check in [
        (
            "ck_inventory_transactions_ordered_quantity_nonnegative",
            "COALESCE(ordered_quantity, 0) >= 0",
        ),
        (
            "ck_inventory_transactions_delivered_quantity_nonnegative",
            "COALESCE(delivered_quantity, 0) >= 0",
        ),
        (
            "ck_inventory_transactions_delivered_not_exceed_ordered",
            "COALESCE(delivered_quantity, 0) <= COALESCE(ordered_quantity, 0)",
        ),
    ]:
        _ensure_check_constraint(bind, "inventory_transactions", name, check)


def _alter_receivable_allocations(bind) -> None:
    if not _table_exists(bind, "receivable_allocations"):
        return
    _ensure_foreign_key(
        bind,
        "receivable_allocations",
        "fk_receivable_allocations_sales_order_id_sales_orders",
        "sales_orders",
        ["sales_order_id"],
        ["id"],
    )
    _ensure_foreign_key(
        bind,
        "receivable_allocations",
        "fk_receivable_allocations_journal_entry_id_journal_entries",
        "journal_entries",
        ["journal_entry_id"],
        ["id"],
    )
    _ensure_foreign_key(
        bind,
        "receivable_allocations",
        "fk_receivable_allocations_line_id_journal_entry_lines",
        "journal_entry_lines",
        ["line_id"],
        ["id"],
    )
    _ensure_foreign_key(
        bind,
        "receivable_allocations",
        "fk_receivable_allocations_reversed_of_id",
        "receivable_allocations",
        ["reversed_of_id"],
        ["id"],
    )
    # 与 ORM ``index=True`` 生成的索引名一致的分配维度索引
    _ensure_index(
        bind,
        "receivable_allocations",
        "ix_receivable_allocations_sales_order_id",
        ["sales_order_id"],
    )
    _ensure_index(
        bind,
        "receivable_allocations",
        "ix_receivable_allocations_journal_entry_id",
        ["journal_entry_id"],
    )
    _ensure_index(
        bind,
        "receivable_allocations",
        "ix_receivable_allocations_line_id",
        ["line_id"],
    )
    _ensure_index(
        bind,
        "receivable_allocations",
        "ix_receivable_allocations_status",
        ["status"],
    )
    _ensure_index(
        bind,
        "receivable_allocations",
        "ix_receivable_allocations_reference_id",
        ["reference_id"],
    )
    _ensure_index(
        bind,
        "receivable_allocations",
        "ix_receivable_allocations_reversed_of_id",
        ["reversed_of_id"],
    )
    for name, check in [
        (
            "ck_receivable_allocations_status_valid",
            "status IN ('unpaid', 'partial', 'paid', 'refunded')",
        ),
        (
            "ck_receivable_allocations_amount_non_negative",
            "COALESCE(amount, 0) >= 0",
        ),
        (
            "ck_receivable_allocations_allocated_amount_non_negative",
            "COALESCE(allocated_amount, 0) >= 0",
        ),
        (
            "ck_receivable_allocations_allocated_le_amount",
            "COALESCE(allocated_amount, 0) <= COALESCE(amount, 0)",
        ),
    ]:
        _ensure_check_constraint(bind, "receivable_allocations", name, check)


def _backfill_sales_orders(bind) -> None:
    """由旧线性 status 映射出正交维度，保留既有数据。"""
    cols = _columns(bind, "sales_orders")
    if "status" not in cols or "state" not in cols:
        return
    bind.execute(
        sa.text(
            "UPDATE sales_orders SET "
            "state='confirmed', invoice_status='invoiced', payment_state='paid' "
            "WHERE status='paid'"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE sales_orders SET state='confirmed', invoice_status='invoiced' "
            "WHERE status='invoiced' AND state='quote'"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE sales_orders SET state='confirmed' WHERE status='delivered' AND state='quote'"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE sales_orders SET state='confirmed' WHERE status='confirmed' AND state='quote'"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE sales_orders SET state='cancel' "
            "WHERE status IN ('cancel','cancelled') AND state != 'cancel'"
        )
    )


def upgrade() -> None:
    bind = op.get_bind()

    # 建表（若缺失）：UOM 表先于 products（products.base_uom_id 引用 uom_units.id），
    # products 先于 sales_order_items（sales_order_items.product_id 引用 products.id）。
    _create_sales_orders_if_missing(bind)
    _create_uom_categories_if_missing(bind)
    _create_uom_units_if_missing(bind)
    _create_products_if_missing(bind)
    _create_sales_order_items_if_missing(bind)
    _create_chart_of_accounts_if_missing(bind)
    _create_journal_entries_if_missing(bind)
    _create_journal_entry_lines_if_missing(bind)
    _create_inventory_transactions_if_missing(bind)
    _create_receivable_allocations_if_missing(bind)

    # 改既有表
    _alter_sales_orders(bind)
    _alter_sales_order_items(bind)
    _alter_chart_of_accounts(bind)
    _alter_journal_entries(bind)
    _alter_journal_entry_lines(bind)
    _alter_products(bind)
    _alter_inventory_transactions(bind)
    # receivable_allocations 依赖 sales_orders / journal_entries / journal_entry_lines，
    # 均在前面建表/改表完成，故最后保障其 FK/CHECK/索引。
    _alter_receivable_allocations(bind)

    # 存量 backfill
    _backfill_sales_orders(bind)


def downgrade() -> None:
    """一次性（disposable）临时 DB 上验证用：恢复旧 schema。

    显式文档化：新维度数据（正交状态/分配/租户复合唯一/DB 约束/UOM/补货字段）
    在 downgrade 后可能被丢弃，不承诺 downgrade 后数据完整保留。
    """
    bind = op.get_bind()

    if _table_exists(bind, "receivable_allocations"):
        op.drop_table("receivable_allocations")

    # 先删除正交维度字段/FK（此时 uom_units / uom_categories 仍存在，
    # 才能正确删除 products.base_uom_id 对 uom_units.id 的外键引用），
    # 之后再删除 UOM 表。
    # 会计 DB 级 CHECK/FK 需先于维度字段删除（posted_balanced / is_credit_note
    # 引用的列随后可能被 _drop_backfill_and_dimensions 删除）。
    _drop_accounting_constraints(bind)
    _drop_backfill_and_dimensions(bind)

    if _table_exists(bind, "uom_units"):
        op.drop_table("uom_units")
    if _table_exists(bind, "uom_categories"):
        op.drop_table("uom_categories")


def _drop_backfill_and_dimensions(bind) -> None:
    """删除本迁移新增的正交维度字段/约束（保留业务数据主体）。"""
    # products 的 UOM/补货字段需在 uom_units 表仍存在时先删 FK，故单独处理
    _drop_products_uom_fields(bind)

    for table, cols in [
        (
            "sales_orders",
            [
                "state",
                "invoice_status",
                "payment_state",
                "sent_date",
                "cancel_date",
                "backorder_of_id",
                "return_of_id",
            ],
        ),
        ("sales_order_items", ["ordered_quantity", "reserved_quantity", "returned_quantity"]),
        ("journal_entries", ["credit_note_of_id", "is_credit_note"]),
        (
            "inventory_transactions",
            [
                "ordered_quantity",
                "delivered_quantity",
                "sales_order_id",
                "sales_order_item_id",
            ],
        ),
    ]:
        if not _table_exists(bind, table):
            continue
        target = {c for c in cols if c in _columns(bind, table)}
        if not target:
            continue
        # 先删引用这些待删列的 FK（如 sales_orders.backorder_of_id 的自引用 FK）。
        # SQLite recreate="auto" 会整表重建消化 FK 列，但 PostgreSQL 用原生
        # ALTER TABLE ... DROP COLUMN，若 FK 仍引用该列会报 "cannot drop column"。
        _drop_foreign_keys_referencing(bind, table, target)
        # 先删依赖这些列的索引，避免 recreate 后残留孤儿索引
        index_names = [
            name
            for name, idx in _indexes(bind, table).items()
            if set(idx.get("column_names") or []) & target
        ]
        # 先删引用这些待删列的 CHECK 约束（如 ck_sales_orders_state_valid /
        # ck_sales_orders_invoice_status_valid），否则 SQLite recreate="auto"
        # 重建表时仍带这些约束 → "no such column: <col>"。
        check_names = [
            str(c["name"])
            for c in sa.inspect(bind).get_check_constraints(table)
            if c.get("name") and any(col in (c.get("sqltext") or "") for col in target)
        ]
        with op.batch_alter_table(table, recreate="auto") as batch_op:
            for name in index_names:
                batch_op.drop_index(name)
            for name in check_names:
                batch_op.drop_constraint(name, type_="check")
            for col in target:
                batch_op.drop_column(col)

    # 删除租户复合唯一约束
    for table, col, name in [
        ("sales_orders", "order_no", "uq_sales_orders_tenant_order_no"),
        ("chart_of_accounts", "code", "uq_chart_of_accounts_tenant_code"),
        ("journal_entries", "entry_no", "uq_journal_entries_tenant_entry_no"),
    ]:
        if not _table_exists(bind, table):
            continue
        constraint_names = {str(c["name"]) for c in sa.inspect(bind).get_unique_constraints(table)}
        if name in constraint_names:
            with op.batch_alter_table(table, recreate="auto") as batch_op:
                batch_op.drop_constraint(name, type_="unique")


def _drop_check_constraint(bind, table: str, name: str) -> None:
    """按名幂等删除 DB 级 CHECK 约束（不存在则跳过）。"""
    if not _table_exists(bind, table):
        return
    names = {str(c["name"]) for c in sa.inspect(bind).get_check_constraints(table)}
    if name not in names:
        return
    with op.batch_alter_table(table, recreate="auto") as batch_op:
        batch_op.drop_constraint(name, type_="check")


def _drop_accounting_constraints(bind) -> None:
    """删除本迁移新增的会计 DB 级 CHECK/FK（保留 schema/列主体）。

    - chart_of_accounts：type / debit_credit CHECK。
    - journal_entries：posted_balanced / is_credit_note CHECK，reversed_of_id /
      credit_note_of_id 自引用 FK。
    - journal_entry_lines：仅删除本迁移新增的 debit/credit CHECK 约束，
      显式保留其既有 entry_id / account_id 外键（schema/列主体不变）。
    """
    if _table_exists(bind, "chart_of_accounts"):
        for name in [
            "ck_chart_of_accounts_type_in_account_types",
            "ck_chart_of_accounts_debit_credit",
        ]:
            _drop_check_constraint(bind, "chart_of_accounts", name)
    if _table_exists(bind, "journal_entries"):
        for name in [
            "ck_journal_entries_posted_balanced",
            "ck_journal_entries_is_credit_note",
        ]:
            _drop_check_constraint(bind, "journal_entries", name)
        _drop_foreign_key(bind, "journal_entries", ["reversed_of_id"], "journal_entries", ["id"])
        _drop_foreign_key(bind, "journal_entries", ["credit_note_of_id"], "journal_entries", ["id"])
    if _table_exists(bind, "journal_entry_lines"):
        for name in [
            "ck_journal_entry_lines_nonnegative",
            "ck_journal_entry_lines_not_both_positive",
        ]:
            _drop_check_constraint(bind, "journal_entry_lines", name)


def _drop_foreign_key(
    bind, table: str, local_cols: list[str], referred: str, remote_cols: list[str]
) -> None:
    """按结构幂等删除 FK。

    SQLite 不持久化 FK 名（反射 name 常为 None），此时交由后续列删除时自动移除；
    PostgreSQL 持久化 FK 名，可直接按名删除。
    """
    if not _table_exists(bind, table):
        return
    fks = [
        fk
        for fk in sa.inspect(bind).get_foreign_keys(table)
        if (
            list(fk.get("constrained_columns") or []) == local_cols
            and fk.get("referred_table") == referred
            and list(fk.get("referred_columns") or []) == remote_cols
        )
    ]
    if not fks:
        return
    with op.batch_alter_table(table, recreate="auto") as batch_op:
        for fk in fks:
            name = fk.get("name")
            if name:
                batch_op.drop_constraint(name, type_="foreignkey")


def _drop_foreign_keys_referencing(bind, table: str, cols: set[str]) -> None:
    """按结构幂等删除 ``table`` 上本地列与 ``cols`` 相交的所有 FK。

    PostgreSQL 的原生 ``ALTER TABLE ... DROP COLUMN`` 会因该列被 FK 引用而失败
    （报 ``cannot drop column ... because other objects depend on it``），因此删除
    列前必须先删这些 FK。SQLite 不持久化 FK 名（name 为 None），交由后续列删除时
    整表重建自动消化，这里仅处理有名字的 FK。
    """
    if not _table_exists(bind, table) or not cols:
        return
    fks = [
        fk
        for fk in sa.inspect(bind).get_foreign_keys(table)
        if set(fk.get("constrained_columns") or []) & cols and fk.get("name")
    ]
    if not fks:
        return
    with op.batch_alter_table(table, recreate="auto") as batch_op:
        for fk in fks:
            batch_op.drop_constraint(fk["name"], type_="foreignkey")


def _drop_products_uom_fields(bind) -> None:
    """删除 products 的 UOM/补货字段及其依赖对象（FK/索引/CHECK），幂等。

    必须在 uom_units / uom_categories 表仍存在时调用，才能正确删除
    products.base_uom_id 对 uom_units.id 的外键引用。
    """
    if not _table_exists(bind, "products"):
        return
    target = {
        c
        for c in ["base_uom_id", "uom_category", "uom_factor", "min_stock", "max_stock"]
        if c in _columns(bind, "products")
    }
    if not target:
        return

    # 先删依赖 UOM 列的 DB 级 CHECK 约束（列仍在，可正常 drop）
    check_names = {str(c["name"]) for c in sa.inspect(bind).get_check_constraints("products")}
    for name in [
        "ck_products_uom_factor_positive",
        "ck_products_min_stock_nonnegative",
        "ck_products_max_stock_nonnegative",
        "ck_products_min_stock_le_max_stock",
    ]:
        if name in check_names:
            with op.batch_alter_table("products", recreate="auto") as batch_op:
                batch_op.drop_constraint(name, type_="check")

    # 删除 products.base_uom_id 的 FK（引用 uom_units.id，仍存在）
    _drop_foreign_key(bind, "products", ["base_uom_id"], "uom_units", ["id"])

    # 删除列及其索引
    index_names = [
        name
        for name, idx in _indexes(bind, "products").items()
        if set(idx.get("column_names") or []) & target
    ]
    with op.batch_alter_table("products", recreate="auto") as batch_op:
        for name in index_names:
            batch_op.drop_index(name)
        for col in target:
            batch_op.drop_column(col)
