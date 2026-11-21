"""Create derived enterprise projections and tenant-owned goal bindings only."""

import sqlalchemy as sa

from alembic import op

revision = "2026_11_21_enterprise_cognition"
down_revision = "2026_11_19_native_checkpoints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "enterprise_state_projections" not in existing:
        op.create_table(
            "enterprise_state_projections",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False, index=True),
            sa.Column("actor_id", sa.String(128), nullable=False),
            sa.Column("mod_id", sa.String(128), nullable=False),
            sa.Column("entity_type", sa.String(32), nullable=False),
            sa.Column("entity_id", sa.String(160), nullable=False),
            sa.Column("snapshot_json", sa.Text(), nullable=False),
            sa.Column("observed_at", sa.Float(), nullable=False),
            sa.Column("expires_at", sa.Float(), nullable=False),
            sa.Column("generation", sa.Integer(), nullable=False),
            sa.UniqueConstraint(
                "tenant_id",
                "actor_id",
                "mod_id",
                "entity_type",
                "entity_id",
                name="uq_enterprise_projection_scope",
            ),
        )
    if "enterprise_event_cursors" not in existing:
        op.create_table(
            "enterprise_event_cursors",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False, index=True),
            sa.Column("mod_id", sa.String(128), nullable=False),
            sa.Column("entity_type", sa.String(32), nullable=False),
            sa.Column("entity_id", sa.String(160), nullable=False),
            sa.Column("generation", sa.Integer(), nullable=False),
            sa.Column("event_id", sa.String(96), nullable=False),
            sa.Column("event_at", sa.Float(), nullable=False),
            sa.Column("source", sa.String(160), nullable=False),
            sa.UniqueConstraint(
                "tenant_id",
                "mod_id",
                "entity_type",
                "entity_id",
                name="uq_enterprise_cursor_scope",
            ),
        )
    if "enterprise_goal_bindings" not in existing:
        op.create_table(
            "enterprise_goal_bindings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("actor_id", sa.String(128), nullable=False),
            sa.Column("mod_id", sa.String(128), nullable=False),
            sa.Column("goal_id", sa.String(96), nullable=False),
            sa.Column("entity_type", sa.String(32), nullable=False),
            sa.Column("entity_id", sa.String(160), nullable=False),
            sa.Column("definition_json", sa.Text(), nullable=False),
            sa.Column("binding_sha256", sa.String(64), nullable=False),
            sa.Column("created_at", sa.String(48), nullable=False),
            sa.UniqueConstraint(
                "tenant_id",
                "actor_id",
                "mod_id",
                "goal_id",
                name="uq_enterprise_goal_scope",
            ),
        )
        op.create_index(
            "ix_enterprise_goal_entity",
            "enterprise_goal_bindings",
            ["tenant_id", "actor_id", "mod_id", "entity_type", "entity_id"],
        )


def downgrade() -> None:
    # Goal references and evidence are retained for existing task traceability.
    pass
