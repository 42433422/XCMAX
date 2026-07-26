"""Adopt runtime foundation tables into the Alembic schema SSOT.

Revision ID: 2026_07_26_runtime_schema_ssot
Revises: 2026_07_26_identity_ssot
Create Date: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "2026_07_26_runtime_schema_ssot"
down_revision: str | Sequence[str] | None = "2026_07_26_identity_ssot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _ensure_index(table: str, index: str, columns: list[str]) -> None:
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
    if index not in indexes:
        op.create_index(index, table, columns, unique=False)


def _ensure_identity_constraints() -> None:
    op.execute(
        """
        UPDATE users
        SET tier = 'personal'
        WHERE tier IS NULL OR tier NOT IN ('personal', 'enterprise', 'admin')
        """
    )
    checks = {item.get("name") for item in sa.inspect(op.get_bind()).get_check_constraints("users")}
    if "ck_users_tier_identity" not in checks:
        with op.batch_alter_table("users") as batch:
            batch.create_check_constraint(
                "ck_users_tier_identity",
                "tier IN ('personal', 'enterprise', 'admin')",
            )

    session_checks = {
        item.get("name") for item in sa.inspect(op.get_bind()).get_check_constraints("sessions")
    }
    if "ck_sessions_account_kind_snapshot" not in session_checks:
        with op.batch_alter_table("sessions") as batch:
            batch.create_check_constraint(
                "ck_sessions_account_kind_snapshot",
                "account_kind IS NULL OR account_kind IN ('personal', 'enterprise', 'admin')",
            )


def upgrade() -> None:
    _ensure_identity_constraints()
    existing = _existing_tables()
    if "ai_action_audit" not in existing:
        op.create_table(
            "ai_action_audit",
            sa.Column(
                "id",
                sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
                primary_key=True,
                autoincrement=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("actor", sa.Text(), nullable=True),
            sa.Column("action", sa.Text(), nullable=False),
            sa.Column(
                "payload",
                sa.JSON().with_variant(JSONB(), "postgresql"),
                nullable=True,
            ),
        )

    if "mobile_relay_desktops" not in existing:
        op.create_table(
            "mobile_relay_desktops",
            sa.Column("relay_id", sa.String(64), primary_key=True),
            sa.Column("pairing_code", sa.String(16), nullable=False, unique=True),
            sa.Column("desktop_token_hash", sa.String(128), nullable=False),
            sa.Column(
                "desktop_label", sa.String(200), nullable=False, server_default=sa.text("''")
            ),
            sa.Column("device_id", sa.String(128), nullable=False, server_default=sa.text("''")),
            sa.Column(
                "relay_base_url", sa.String(512), nullable=False, server_default=sa.text("''")
            ),
            sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'pending'")),
            sa.Column("mobile_user_id", sa.Integer(), nullable=True),
            sa.Column(
                "mobile_username", sa.String(200), nullable=False, server_default=sa.text("''")
            ),
            sa.Column(
                "capabilities_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")
            ),
            sa.Column("last_seen_at", sa.String(64), nullable=True),
            sa.Column("expires_at", sa.String(64), nullable=False),
            sa.Column("created_at", sa.String(64), nullable=False),
            sa.Column("updated_at", sa.String(64), nullable=False),
        )
    _ensure_index(
        "mobile_relay_desktops",
        "ix_mobile_relay_desktops_user",
        ["mobile_user_id"],
    )

    if "mobile_relay_tasks" not in existing:
        op.create_table(
            "mobile_relay_tasks",
            sa.Column("task_id", sa.String(64), primary_key=True),
            sa.Column("relay_id", sa.String(64), nullable=False),
            sa.Column(
                "kind", sa.String(64), nullable=False, server_default=sa.text("'codex.invoke'")
            ),
            sa.Column("payload_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'queued'")),
            sa.Column("result_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.String(64), nullable=False),
            sa.Column("updated_at", sa.String(64), nullable=False),
            sa.Column("claimed_at", sa.String(64), nullable=True),
            sa.Column("completed_at", sa.String(64), nullable=True),
        )
    _ensure_index(
        "mobile_relay_tasks",
        "ix_mobile_relay_tasks_relay_status",
        ["relay_id", "status", "created_at"],
    )


def downgrade() -> None:
    # This revision adopts tables that older runtimes may already own and that
    # contain durable audit/relay data. A downgrade must not guess provenance or
    # destroy those rows.
    pass
