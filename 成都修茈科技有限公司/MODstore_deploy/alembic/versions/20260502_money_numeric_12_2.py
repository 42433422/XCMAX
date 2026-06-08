"""金额列 Float → Numeric(12,2)（PostgreSQL）。

Revision ID: 20260502_money
Revises:
Create Date: 2026-05-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260502_money"
down_revision = None
branch_labels = None
depends_on = None


def _is_postgres(bind) -> bool:
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    bind = op.get_bind()
    if not _is_postgres(bind):
        return
    stmts = [
        "ALTER TABLE wallets ALTER COLUMN balance TYPE NUMERIC(12,2) USING round(balance::numeric, 2)",
        "ALTER TABLE transactions ALTER COLUMN amount TYPE NUMERIC(12,2) USING round(amount::numeric, 2)",
        "ALTER TABLE account_experience_ledger ALTER COLUMN amount TYPE NUMERIC(12,2) USING round(amount::numeric, 2)",
        "ALTER TABLE purchases ALTER COLUMN amount TYPE NUMERIC(12,2) USING round(amount::numeric, 2)",
        "ALTER TABLE refund_requests ALTER COLUMN amount TYPE NUMERIC(12,2) USING round(amount::numeric, 2)",
        "ALTER TABLE plan_templates ALTER COLUMN price TYPE NUMERIC(12,2) USING round(price::numeric, 2)",
        "ALTER TABLE catalog_items ALTER COLUMN price TYPE NUMERIC(12,2) USING round(price::numeric, 2)",
        "ALTER TABLE ai_model_prices ALTER COLUMN input_price_per_1k TYPE NUMERIC(12,6) USING round(input_price_per_1k::numeric, 6)",
        "ALTER TABLE ai_model_prices ALTER COLUMN output_price_per_1k TYPE NUMERIC(12,6) USING round(output_price_per_1k::numeric, 6)",
        "ALTER TABLE ai_model_prices ALTER COLUMN min_charge TYPE NUMERIC(12,2) USING round(min_charge::numeric, 2)",
        "ALTER TABLE chat_messages ALTER COLUMN charge_amount TYPE NUMERIC(12,2) USING round(charge_amount::numeric, 2)",
        "ALTER TABLE llm_call_logs ALTER COLUMN charge_amount TYPE NUMERIC(12,2) USING round(charge_amount::numeric, 2)",
    ]
    for sql in stmts:
        op.execute(sa.text(sql))


def downgrade() -> None:
    bind = op.get_bind()
    if not _is_postgres(bind):
        return
    rev = [
        ("wallets", "balance", "double precision"),
        ("transactions", "amount", "double precision"),
        ("account_experience_ledger", "amount", "double precision"),
        ("purchases", "amount", "double precision"),
        ("refund_requests", "amount", "double precision"),
        ("plan_templates", "price", "double precision"),
        ("catalog_items", "price", "double precision"),
        ("ai_model_prices", "input_price_per_1k", "double precision"),
        ("ai_model_prices", "output_price_per_1k", "double precision"),
        ("ai_model_prices", "min_charge", "double precision"),
        ("chat_messages", "charge_amount", "double precision"),
        ("llm_call_logs", "charge_amount", "double precision"),
    ]
    for table, col, typ in rev:
        op.execute(sa.text(f"ALTER TABLE {table} ALTER COLUMN {col} TYPE {typ} USING {col}::double precision"))
