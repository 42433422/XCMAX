"""llm_billing_settings: 全局 LLM 默认价与服务费倍率（运营可改，不必改环境变量）。"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260601_llm_billing_settings"
down_revision = "20260526_users_deleted_at"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        row = bind.execute(
            sa.text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"),
            {"n": name},
        ).fetchone()
        return row is not None
    row = bind.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :n"),
        {"n": name},
    ).fetchone()
    return row is not None


def upgrade() -> None:
    if _table_exists("llm_billing_settings"):
        return
    op.create_table(
        "llm_billing_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("service_fee_multiplier", sa.Numeric(8, 4), nullable=True),
        sa.Column("default_input_price_per_1k", sa.Numeric(12, 6), nullable=True),
        sa.Column("default_output_price_per_1k", sa.Numeric(12, 6), nullable=True),
        sa.Column("default_min_charge", sa.Numeric(12, 2), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.execute(
        sa.text(
            "INSERT INTO llm_billing_settings (id, service_fee_multiplier, "
            "default_input_price_per_1k, default_output_price_per_1k, default_min_charge) "
            "VALUES (1, NULL, NULL, NULL, NULL)"
        )
    )


def downgrade() -> None:
    if _table_exists("llm_billing_settings"):
        op.drop_table("llm_billing_settings")
