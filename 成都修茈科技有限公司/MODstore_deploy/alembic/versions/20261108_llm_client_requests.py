"""Client idempotency ledger for billed chat streams."""

import sqlalchemy as sa

from alembic import op

revision = "20261108_llm_client_requests"
down_revision = "20261107_ticket_lock_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "llm_client_requests" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "llm_client_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_request_id", sa.String(128), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="processing"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("done_json", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "user_id", "client_request_id", name="uq_llm_client_request"
        ),
    )
    op.create_index(
        "ix_llm_client_requests_user_id", "llm_client_requests", ["user_id"]
    )


def downgrade() -> None:
    if "llm_client_requests" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_index(
            "ix_llm_client_requests_user_id", table_name="llm_client_requests"
        )
        op.drop_table("llm_client_requests")
