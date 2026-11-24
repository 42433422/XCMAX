"""Adaptive per-model concurrency limits shared by every worker."""

import sqlalchemy as sa

from alembic import op

revision = "20261124_model_concurrency"
down_revision = "20261121_xiaoc_life"
branch_labels = None
depends_on = None

SEEDS = {
    "litellm/xcmax-xiaomi-fast": 12,
    "litellm/xcmax-xiaomi-code": 12,
    "litellm/xcmax-para-coding": 12,
    "litellm/xcmax-doubao-code": 8,
    "litellm/xcmax-kimi-code": 8,
    "litellm/xcmax-kimi-k3-256k": 8,
    "litellm/xcmax-kimi-k3-1-pro": 8,
}


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "llm_model_concurrency" not in tables:
        op.create_table(
            "llm_model_concurrency",
            sa.Column("model_key", sa.String(160), primary_key=True),
            sa.Column("limit_value", sa.Integer(), nullable=False),
            sa.Column("min_limit", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("max_limit", sa.Integer(), nullable=False),
            sa.Column("success_streak", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
    if "llm_model_leases" not in tables:
        op.create_table(
            "llm_model_leases",
            sa.Column("lease_id", sa.String(32), primary_key=True),
            sa.Column("model_key", sa.String(160), nullable=False, index=True),
            sa.Column(
                "acquired_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        )
    concurrency = sa.table(
        "llm_model_concurrency",
        sa.column("model_key", sa.String),
        sa.column("limit_value", sa.Integer),
        sa.column("min_limit", sa.Integer),
        sa.column("max_limit", sa.Integer),
        sa.column("updated_at", sa.DateTime),
    )
    bind = op.get_bind()
    for model_key, limit in SEEDS.items():
        exists = bind.execute(
            sa.text("SELECT 1 FROM llm_model_concurrency WHERE model_key = :key"),
            {"key": model_key},
        ).first()
        if exists:
            continue
        bind.execute(
            concurrency.insert().values(
                model_key=model_key,
                limit_value=limit,
                min_limit=1,
                max_limit=limit,
                updated_at=sa.func.now(),
            )
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "llm_model_leases" in tables:
        op.drop_table("llm_model_leases")
    if "llm_model_concurrency" in tables:
        op.drop_table("llm_model_concurrency")
