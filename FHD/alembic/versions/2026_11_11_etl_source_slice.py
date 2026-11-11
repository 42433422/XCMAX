"""Allow one sheet row to persist as several ELT slices."""

import sqlalchemy as sa

from alembic import op

revision = "2026_11_11_etl_source_slice"
down_revision = "2026_11_11_agent_permissions"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("etl_run_rows") as batch:
        batch.add_column(
            sa.Column("source_slice", sa.Integer(), nullable=False, server_default="0")
        )
        batch.drop_constraint("uq_etl_run_source_row", type_="unique")
        batch.create_unique_constraint(
            "uq_etl_run_source_slice",
            ["run_id", "source_sheet", "source_row", "source_slice"],
        )


def downgrade():
    with op.batch_alter_table("etl_run_rows") as batch:
        batch.drop_constraint("uq_etl_run_source_slice", type_="unique")
        batch.create_unique_constraint(
            "uq_etl_run_source_row", ["run_id", "source_sheet", "source_row"]
        )
        batch.drop_column("source_slice")
