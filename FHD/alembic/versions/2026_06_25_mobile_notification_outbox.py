"""mobile self-push offline outbox

Revision ID: 2026_06_25_mobile_outbox
Revises: 2026_06_22_baseline
Create Date: 2026-06-25

极光 JPush 移除后,自建推送的后台离线队列。notify_user 入队,
客户端 /api/notifications/pending 轮询拉取并标记 delivered。
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "2026_06_25_mobile_outbox"
down_revision: Union[str, Sequence[str], None] = "2026_06_22_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "mobile_notification_outbox"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("route", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("channel", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("data_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("delivered", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_mobile_outbox_user_id", _TABLE, ["user_id"])
    op.create_index("ix_mobile_outbox_delivered", _TABLE, ["delivered"])
    op.create_index("ix_mobile_outbox_created_at", _TABLE, ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(_TABLE):
        return
    op.drop_index("ix_mobile_outbox_created_at", table_name=_TABLE)
    op.drop_index("ix_mobile_outbox_delivered", table_name=_TABLE)
    op.drop_index("ix_mobile_outbox_user_id", table_name=_TABLE)
    op.drop_table(_TABLE)
