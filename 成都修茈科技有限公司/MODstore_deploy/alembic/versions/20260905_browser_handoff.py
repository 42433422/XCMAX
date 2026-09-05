"""Add one-use wallet and plans browser login codes.

Revision ID: 20260905_browser_handoff
Revises: 20260904_asset_install_cmd
"""

import sqlalchemy as sa
from alembic import op

revision = "20260905_browser_handoff"
down_revision = "20260904_asset_install_cmd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "browser_handoff_codes" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "browser_handoff_codes",
        sa.Column("code_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("credential_fingerprint", sa.String(64), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("target", sa.String(1024), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_browser_handoff_codes_expires_at", "browser_handoff_codes", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_table("browser_handoff_codes")
