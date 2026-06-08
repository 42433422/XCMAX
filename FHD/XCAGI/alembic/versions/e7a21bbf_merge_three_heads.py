"""merge_three_heads

Revision ID: e7a21bbf_merge
Revises: merge_customers_to_products, xcagi_v5_miniprogram
Create Date: 2026-04-11

Merge Alembic heads: customers merge branch + miniprogram/inventory chain.
"""
from typing import Sequence, Union

revision: str = "e7a21bbf_merge"
down_revision: Union[str, Sequence[str], None] = (
    "merge_customers_to_products",
    "xcagi_v5_miniprogram",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
