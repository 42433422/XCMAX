"""merge_three_alembic_heads

Revision ID: f8c2e1d0abb7
Revises: c4a9f8e1d2b3, merge_customers_to_products, xcagi_v5_miniprogram
Create Date: 2026-04-19

Unifies three independent Alembic heads into a single lineage so
`alembic upgrade head` is deterministic and downgrades can target one head.
"""
from typing import Sequence, Union

revision: str = "f8c2e1d0abb7"
down_revision: Union[str, Sequence[str], None] = (
    "c4a9f8e1d2b3",
    "merge_customers_to_products",
    "xcagi_v5_miniprogram",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
