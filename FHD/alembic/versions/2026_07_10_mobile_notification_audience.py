"""Partition mobile push devices and outbox rows by trusted audience.

Revision ID: 20260710_mobile_audience
Revises: 2026_07_09_ai_approval
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260710_mobile_audience"
down_revision: str | Sequence[str] | None = "2026_07_09_ai_approval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEVICE_TABLE = "mobile_device_tokens"
_OUTBOX_TABLE = "mobile_notification_outbox"


def _column_names(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table)}


def _index_names(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {str(index["name"]) for index in inspector.get_indexes(table)}


def _unique_names(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {
        str(constraint["name"])
        for constraint in inspector.get_unique_constraints(table)
        if constraint.get("name")
    }


def _tenant_is_nullable(bind, table: str) -> bool:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return False
    for column in inspector.get_columns(table):
        if column["name"] == "tenant_id":
            return bool(column.get("nullable", True))
    return False


def _backfill_tenant(bind, table: str, *, all_rows: bool) -> None:
    predicate = "1 = 1" if all_rows else "tenant_id IS NULL"
    user_columns = _column_names(bind, "users")
    if "tenant_id" in user_columns:
        op.execute(
            sa.text(
                f"UPDATE {table} SET tenant_id = COALESCE("
                f"(SELECT users.tenant_id FROM users WHERE users.id = {table}.user_id), 0) "
                f"WHERE {predicate}"
            )
        )
    else:
        op.execute(sa.text(f"UPDATE {table} SET tenant_id = 0 WHERE {predicate}"))


def upgrade() -> None:
    bind = op.get_bind()
    device_columns = _column_names(bind, _DEVICE_TABLE)
    if device_columns:
        if "notification_audience" not in device_columns:
            op.add_column(
                _DEVICE_TABLE,
                sa.Column(
                    "notification_audience",
                    sa.String(length=32),
                    nullable=False,
                    server_default="enterprise",
                ),
            )
        device_tenant_missing = "tenant_id" not in device_columns
        if device_tenant_missing:
            op.add_column(
                _DEVICE_TABLE,
                sa.Column(
                    "tenant_id", sa.Integer(), nullable=True, server_default=sa.text("0")
                ),
            )
        _backfill_tenant(bind, _DEVICE_TABLE, all_rows=device_tenant_missing)
        if _tenant_is_nullable(bind, _DEVICE_TABLE):
            with op.batch_alter_table(_DEVICE_TABLE) as batch_op:
                batch_op.alter_column(
                    "tenant_id",
                    existing_type=sa.Integer(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
        indexes = _index_names(bind, _DEVICE_TABLE)
        if "ix_mobile_device_tokens_notification_audience" not in indexes:
            op.create_index(
                "ix_mobile_device_tokens_notification_audience",
                _DEVICE_TABLE,
                ["notification_audience"],
            )
        if "ix_mobile_device_tokens_tenant_id" not in indexes:
            op.create_index("ix_mobile_device_tokens_tenant_id", _DEVICE_TABLE, ["tenant_id"])

    outbox_columns = _column_names(bind, _OUTBOX_TABLE)
    if outbox_columns:
        if "notification_audience" not in outbox_columns:
            op.add_column(
                _OUTBOX_TABLE,
                sa.Column(
                    "notification_audience",
                    sa.String(length=32),
                    nullable=False,
                    server_default="enterprise",
                ),
            )
        outbox_tenant_missing = "tenant_id" not in outbox_columns
        if outbox_tenant_missing:
            op.add_column(
                _OUTBOX_TABLE,
                sa.Column(
                    "tenant_id", sa.Integer(), nullable=True, server_default=sa.text("0")
                ),
            )
        if "event_id" not in outbox_columns:
            op.add_column(
                _OUTBOX_TABLE,
                sa.Column("event_id", sa.String(length=256), nullable=True),
            )
        _backfill_tenant(bind, _OUTBOX_TABLE, all_rows=outbox_tenant_missing)
        if _tenant_is_nullable(bind, _OUTBOX_TABLE):
            with op.batch_alter_table(_OUTBOX_TABLE) as batch_op:
                batch_op.alter_column(
                    "tenant_id",
                    existing_type=sa.Integer(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
        indexes = _index_names(bind, _OUTBOX_TABLE)
        if "ix_mobile_notification_outbox_notification_audience" not in indexes:
            op.create_index(
                "ix_mobile_notification_outbox_notification_audience",
                _OUTBOX_TABLE,
                ["notification_audience"],
            )
        if "ix_mobile_notification_outbox_tenant_id" not in indexes:
            op.create_index("ix_mobile_notification_outbox_tenant_id", _OUTBOX_TABLE, ["tenant_id"])
        if "uq_mobile_outbox_scope_event" not in _unique_names(bind, _OUTBOX_TABLE):
            with op.batch_alter_table(_OUTBOX_TABLE) as batch_op:
                batch_op.create_unique_constraint(
                    "uq_mobile_outbox_scope_event",
                    ["user_id", "notification_audience", "tenant_id", "event_id"],
                )


def downgrade() -> None:
    bind = op.get_bind()
    for table in (_OUTBOX_TABLE, _DEVICE_TABLE):
        columns = _column_names(bind, table)
        if not columns:
            continue
        indexes = _index_names(bind, table)
        for name in (
            f"ix_{table}_tenant_id",
            f"ix_{table}_notification_audience",
        ):
            if name in indexes:
                op.drop_index(name, table_name=table)
        with op.batch_alter_table(table) as batch_op:
            if table == _OUTBOX_TABLE and "uq_mobile_outbox_scope_event" in _unique_names(
                bind, table
            ):
                batch_op.drop_constraint("uq_mobile_outbox_scope_event", type_="unique")
            if table == _OUTBOX_TABLE and "event_id" in columns:
                batch_op.drop_column("event_id")
            if "tenant_id" in columns:
                batch_op.drop_column("tenant_id")
            if "notification_audience" in columns:
                batch_op.drop_column("notification_audience")
