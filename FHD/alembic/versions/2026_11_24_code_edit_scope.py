"""Reconcile published proposal schemas without changing claim outcomes."""

import json

import sqlalchemy as sa

from alembic import op

revision = "2026_11_24_code_edit_scope"
down_revision = "2026_11_24_merge_account_edit"
branch_labels = None
depends_on = None

_TABLE = "code_edit_proposals"


def upgrade() -> None:
    connection = op.get_bind()
    columns = {column["name"] for column in sa.inspect(connection).get_columns(_TABLE)}
    if {"user_id", "scope_json", "state"} <= columns:
        return
    if not {"owner_user_id", "tenant_id", "workspace_root", "apply_state", "created_at"} <= columns:
        raise ValueError("unrecognized code_edit_proposals schema; claims were not changed")

    if "scope_json" not in columns:
        op.add_column(_TABLE, sa.Column("scope_json", sa.Text(), nullable=True))
    proposals = sa.Table(_TABLE, sa.MetaData(), autoload_with=connection)
    for row in connection.execute(sa.select(proposals)).mappings():
        scope = json.dumps(
            {
                "user_id": row["owner_user_id"],
                "tenant_id": row["tenant_id"],
                "workspace_root": row["workspace_root"],
            },
            sort_keys=True,
        )
        connection.execute(
            proposals.update().where(proposals.c.edit_id == row["edit_id"]).values(scope_json=scope)
        )

    # SQLite's batch copy preserves all rows, claim states and legacy metadata.
    # Retained metadata becomes optional for proposals created by the current ORM.
    with op.batch_alter_table(_TABLE) as batch:
        batch.alter_column("owner_user_id", new_column_name="user_id", existing_type=sa.Integer())
        batch.alter_column(
            "apply_state", new_column_name="state", existing_type=sa.String(16), server_default=None
        )
        batch.alter_column("edit_id", existing_type=sa.String(40), type_=sa.String(64))
        batch.alter_column("scope_json", existing_type=sa.Text(), nullable=False)
        batch.alter_column("workspace_root", existing_type=sa.Text(), nullable=True)
        batch.alter_column("created_at", existing_type=sa.DateTime(), nullable=True)


def downgrade() -> None:
    # Keep durable claims and consumed records; rollback must never reopen them.
    pass
