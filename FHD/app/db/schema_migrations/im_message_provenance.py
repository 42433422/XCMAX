"""The im_messages step of revision 2026_08_31_enterprise_cs_ai, and no later schema.

The revision and desktop compatibility entry point share these exact definitions.
Keeping them here avoids a second runtime-owned definition of the same migration.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic.operations import Operations
from sqlalchemy.schema import CreateColumn


def apply_message_provenance(operations: Operations) -> None:
    bind = operations.get_bind()
    inspector = sa.inspect(bind)
    if "im_messages" not in set(inspector.get_table_names()):
        return
    existing = {str(row.get("name") or "") for row in inspector.get_columns("im_messages")}
    columns = (
        sa.Column("origin", sa.String(length=32), nullable=False, server_default="user"),
        sa.Column("operator_user_id", sa.Integer(), nullable=True),
    )
    for column in columns:
        if column.name in existing:
            continue
        if bind.dialect.name == "postgresql":
            # Preserve startup's concurrent-repair tolerance, including Alembic 1.13
            # where Operations.add_column did not yet accept if_not_exists.
            definition = str(CreateColumn(column).compile(dialect=bind.dialect))
            operations.execute(
                sa.text(f"ALTER TABLE im_messages ADD COLUMN IF NOT EXISTS {definition}")
            )
        else:
            operations.add_column("im_messages", column)
    indexes = {str(row.get("name") or "") for row in sa.inspect(bind).get_indexes("im_messages")}
    if "ix_im_messages_operator_user_id" not in indexes:
        operations.create_index(
            "ix_im_messages_operator_user_id",
            "im_messages",
            ["operator_user_id"],
            if_not_exists=True,
        )
