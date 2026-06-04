"""cs_delivery_signoffs (PostgreSQL)

Revision ID: 2026_05_31_cs_delivery_signoffs
Revises: 2026_05_31_model_payment_orders
"""

import sqlalchemy as sa
from alembic import op

revision = "2026_05_31_cs_delivery_signoffs"
down_revision = "2026_05_31_model_payment_orders"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cs_delivery_signoffs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("opportunity_id", sa.Integer(), nullable=False),
        sa.Column("market_user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("signed_by", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("signed_role", sa.String(length=32), nullable=False, server_default="customer"),
        sa.Column("attachment_url", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("signed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cs_delivery_signoffs_opportunity_id", "cs_delivery_signoffs", ["opportunity_id"])
    op.create_index("ix_cs_delivery_signoffs_market_user_id", "cs_delivery_signoffs", ["market_user_id"])
    op.create_index("ix_cs_delivery_signoffs_status", "cs_delivery_signoffs", ["status"])
    op.create_index(
        "ix_cs_delivery_signoffs_opp_status",
        "cs_delivery_signoffs",
        ["opportunity_id", "status"],
    )


def downgrade():
    op.drop_index("ix_cs_delivery_signoffs_opp_status", table_name="cs_delivery_signoffs")
    op.drop_index("ix_cs_delivery_signoffs_status", table_name="cs_delivery_signoffs")
    op.drop_index("ix_cs_delivery_signoffs_market_user_id", table_name="cs_delivery_signoffs")
    op.drop_index("ix_cs_delivery_signoffs_opportunity_id", table_name="cs_delivery_signoffs")
    op.drop_table("cs_delivery_signoffs")
