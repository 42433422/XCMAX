"""Persist payment identities and web-refresh replay receipts (additive migration)."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "2026_10_20_receipt_identity"
down_revision = "2026_10_10_credit_journal_cols"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "receivable_allocations" not in inspector.get_table_names():
        raise RuntimeError("receivable_allocations missing; restore the baseline before upgrading")
    present = {column["name"] for column in inspector.get_columns("receivable_allocations")}
    for name, width in (("request_key", 128), ("request_fingerprint", 64)):
        if name not in present:
            op.add_column("receivable_allocations", sa.Column(name, sa.String(width), nullable=True))
    indexed = {index["name"] for index in sa.inspect(bind).get_indexes("receivable_allocations")}
    if "uq_receivable_order_request" not in indexed:
        op.create_index("uq_receivable_order_request", "receivable_allocations",
                        ["sales_order_id", "request_key"], unique=True)

    if "web_refresh_token_uses" not in sa.inspect(bind).get_table_names():
        op.create_table("web_refresh_token_uses",
                        sa.Column("jti", sa.String(64), primary_key=True),
                        sa.Column("expires_at", sa.BigInteger(), nullable=False))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("web_refresh_token_uses")}
    if "ix_web_refresh_token_uses_expires_at" not in indexes:
        op.create_index("ix_web_refresh_token_uses_expires_at", "web_refresh_token_uses", ["expires_at"])


def downgrade() -> None:
    # Additive fields are safe for old readers. Dropping identities would allow
    # already-processed requests to be posted again after an upgrade/rollback.
    pass
