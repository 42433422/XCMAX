"""Persist the management enterprise's unique XiaoC and lifecycle evidence."""

import sqlalchemy as sa

from alembic import op

revision = "20261121_xiaoc_life"
down_revision = "20261119_personal_allowance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("xiaoc_life_state"):
        op.create_table(
            "xiaoc_life_state",
            sa.Column("identity_id", sa.String(64), primary_key=True),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("state_json", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if not sa.inspect(op.get_bind()).has_table("xiaoc_life_events"):
        op.create_table(
            "xiaoc_life_events",
            sa.Column("id", sa.String(96), primary_key=True),
            sa.Column(
                "identity_id",
                sa.String(64),
                sa.ForeignKey("xiaoc_life_state.identity_id"),
                nullable=False,
            ),
            sa.Column("kind", sa.String(32), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("summary", sa.String(1000), nullable=False),
            sa.Column("evidence_json", sa.Text(), nullable=False),
            sa.Column("details_json", sa.Text(), nullable=False),
            sa.Column("model", sa.String(320), nullable=False),
            sa.Column("actual_tokens", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    index = "ix_xiaoc_life_events_identity_time"
    if index not in {
        row["name"] for row in sa.inspect(op.get_bind()).get_indexes("xiaoc_life_events")
    }:
        op.create_index(index, "xiaoc_life_events", ["identity_id", "created_at"])


def downgrade() -> None:
    for table in ("xiaoc_life_events", "xiaoc_life_state"):
        if sa.inspect(op.get_bind()).has_table(table):
            op.drop_table(table)
