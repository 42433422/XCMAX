"""Reconcile the first published proposal schema without resetting write claims."""

import json

import sqlalchemy as sa

from alembic import op

revision = "2026_11_24_code_edit_scope"
down_revision = "2026_11_24_merge_account_edit"
branch_labels = None
depends_on = None

_TABLE = "code_edit_proposals"
_CURRENT = {"edit_id", "user_id", "scope_json", "payload_json", "state"}
_LEGACY = {
    "edit_id",
    "owner_user_id",
    "tenant_id",
    "workspace_root",
    "payload_json",
    "apply_state",
    "created_at",
}


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if not inspector.has_table(_TABLE):
        raise RuntimeError("Code proposal reconciliation requires the original proposal table")
    column_specs = {column["name"]: column for column in inspector.get_columns(_TABLE)}
    columns = set(column_specs)
    if columns >= _CURRENT and not columns.intersection({"owner_user_id", "apply_state"}):
        return
    if not columns >= _LEGACY or columns.intersection({"user_id", "state"}):
        raise RuntimeError("Cannot safely reconcile an unrecognized code proposal schema")
    # The published implementation may stop after adding this nullable column.
    # Its values are derived again only after every original identity is validated.
    if "scope_json" in columns and (
        not column_specs["scope_json"]["nullable"]
        or not isinstance(column_specs["scope_json"]["type"], sa.Text)
    ):
        raise RuntimeError("Cannot safely reconcile an unrecognized partial code proposal scope")

    legacy = sa.table(
        _TABLE,
        sa.column("edit_id", sa.String()),
        sa.column("owner_user_id", sa.Integer()),
        sa.column("tenant_id", sa.Integer()),
        sa.column("workspace_root", sa.Text()),
        sa.column("apply_state", sa.String()),
    )
    # SQLite's legacy driver does not start a real transaction for DDL. A
    # savepoint covers add/backfill/batch-copy together, including injected errors.
    with connection.begin_nested():
        if connection.dialect.name == "sqlite":
            connection.execute(sa.update(legacy).where(sa.false()).values(edit_id=legacy.c.edit_id))
        elif connection.dialect.name == "postgresql":
            connection.execute(sa.text("LOCK TABLE code_edit_proposals IN ACCESS EXCLUSIVE MODE"))
        else:
            raise RuntimeError("Code proposal reconciliation requires SQLite or PostgreSQL")
        scopes = []
        for row in connection.execute(sa.select(legacy)).mappings():
            if (
                not isinstance(row["owner_user_id"], int)
                or (row["tenant_id"] is not None and not isinstance(row["tenant_id"], int))
                or not isinstance(row["workspace_root"], str)
                or not row["workspace_root"].strip()
                or not isinstance(row["apply_state"], str)
            ):
                raise RuntimeError("cannot safely migrate code proposal ownership or state")
            scopes.append(
                {
                    "original_id": row["edit_id"],
                    "original_scope": json.dumps(
                        {
                            "user_id": row["owner_user_id"],
                            "tenant_id": row["tenant_id"],
                            "workspace_root": row["workspace_root"],
                        },
                        sort_keys=True,
                    ),
                }
            )

        # Validate every scope before any DDL. Payload bytes and state values are
        # never decoded or remapped; every non-pending state remains non-pending.
        if "scope_json" not in columns:
            op.add_column(_TABLE, sa.Column("scope_json", sa.Text(), nullable=True))
        target = sa.table(_TABLE, sa.column("edit_id"), sa.column("scope_json"))
        if scopes:
            connection.execute(
                sa.update(target)
                .where(target.c.edit_id == sa.bindparam("original_id"))
                .values(scope_json=sa.bindparam("original_scope")),
                scopes,
            )
        with op.batch_alter_table(_TABLE) as batch:
            batch.alter_column("edit_id", existing_type=sa.String(40), type_=sa.String(64))
            batch.alter_column(
                "owner_user_id", existing_type=sa.Integer(), new_column_name="user_id"
            )
            batch.alter_column(
                "apply_state",
                existing_type=sa.String(16),
                new_column_name="state",
                server_default=None,
            )
            batch.alter_column("scope_json", existing_type=sa.Text(), nullable=False)
            # Retain original metadata without making the new ORM invent values
            # for fields that are now carried by its immutable scope JSON.
            batch.alter_column("workspace_root", existing_type=sa.Text(), nullable=True)
            batch.alter_column("created_at", existing_type=sa.DateTime(), nullable=True)


def downgrade() -> None:
    # Keep scope evidence and uncertain/applied claims through version rollback.
    pass
