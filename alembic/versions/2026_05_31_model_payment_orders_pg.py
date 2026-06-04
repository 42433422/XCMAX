"""model_payment orders and entitlements (PostgreSQL SoT)

Revision ID: 2026_05_31_model_payment_orders
Revises: 2026_05_26_mobile_device_push
"""

import sqlalchemy as sa
from alembic import op

revision = "2026_05_31_model_payment_orders"
down_revision = "2026_05_26_mobile_device_push"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "model_payment_orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("out_trade_no", sa.String(length=64), nullable=False),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("amount_yuan", sa.String(length=32), nullable=False, server_default="0.00"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_payment"),
        sa.Column("trade_no", sa.String(length=64), nullable=True),
        sa.Column("market_user_id", sa.Integer(), nullable=True),
        sa.Column("notify_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_notify_at", sa.DateTime(), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("raw_notify", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("out_trade_no", name="uq_model_payment_orders_out_trade_no"),
    )
    op.create_index("ix_model_payment_orders_out_trade_no", "model_payment_orders", ["out_trade_no"])
    op.create_index("ix_model_payment_orders_plan_id", "model_payment_orders", ["plan_id"])
    op.create_index("ix_model_payment_orders_status", "model_payment_orders", ["status"])
    op.create_index("ix_model_payment_orders_market_user_id", "model_payment_orders", ["market_user_id"])
    op.create_index(
        "ix_model_payment_orders_plan_status",
        "model_payment_orders",
        ["plan_id", "status"],
    )

    op.create_table(
        "model_payment_entitlements",
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("purchase_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_paid_at", sa.DateTime(), nullable=True),
        sa.Column("last_paid_at", sa.DateTime(), nullable=True),
        sa.Column("last_out_trade_no", sa.String(length=64), nullable=True),
        sa.Column("last_trade_no", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("plan_id"),
    )
    op.create_index(
        "ix_model_payment_entitlements_last_paid_at",
        "model_payment_entitlements",
        ["last_paid_at"],
    )


def downgrade():
    op.drop_index("ix_model_payment_entitlements_last_paid_at", table_name="model_payment_entitlements")
    op.drop_table("model_payment_entitlements")
    op.drop_index("ix_model_payment_orders_plan_status", table_name="model_payment_orders")
    op.drop_index("ix_model_payment_orders_market_user_id", table_name="model_payment_orders")
    op.drop_index("ix_model_payment_orders_status", table_name="model_payment_orders")
    op.drop_index("ix_model_payment_orders_plan_id", table_name="model_payment_orders")
    op.drop_index("ix_model_payment_orders_out_trade_no", table_name="model_payment_orders")
    op.drop_table("model_payment_orders")
