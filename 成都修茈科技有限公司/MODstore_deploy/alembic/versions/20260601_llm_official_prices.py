"""ai_model_prices 官网价字段 + llm_billing_settings.official_markup_multiplier"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260601_llm_official_prices"
down_revision = "20260601_llm_billing_settings"
branch_labels = None
depends_on = None


def _col_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        rows = bind.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
        return any(row[1] == column for row in rows)
    row = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    ).fetchone()
    return row is not None


def upgrade() -> None:
    if not _col_exists("llm_billing_settings", "official_markup_multiplier"):
        op.add_column(
            "llm_billing_settings",
            sa.Column("official_markup_multiplier", sa.Numeric(8, 4), nullable=True),
        )
    for col, typ in (
        ("official_input_price_per_1k", sa.Numeric(12, 6)),
        ("official_output_price_per_1k", sa.Numeric(12, 6)),
        ("official_min_charge", sa.Numeric(12, 2)),
        ("official_source", sa.String(512)),
    ):
        if not _col_exists("ai_model_prices", col):
            op.add_column("ai_model_prices", sa.Column(col, typ, nullable=True))
    if not _col_exists("ai_model_prices", "official_synced_at"):
        op.add_column("ai_model_prices", sa.Column("official_synced_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    for col in (
        "official_synced_at",
        "official_source",
        "official_min_charge",
        "official_output_price_per_1k",
        "official_input_price_per_1k",
    ):
        if _col_exists("ai_model_prices", col):
            op.drop_column("ai_model_prices", col)
    if _col_exists("llm_billing_settings", "official_markup_multiplier"):
        op.drop_column("llm_billing_settings", "official_markup_multiplier")
