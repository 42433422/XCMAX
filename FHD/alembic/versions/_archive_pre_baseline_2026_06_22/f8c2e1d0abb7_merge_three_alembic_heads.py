"""merge_three_alembic_heads

Revision ID: f8c2e1d0abb7
Revises: c4a9f8e1d2b3, merge_customers_to_products
Create Date: 2026-04-19

Unifies the independent Alembic heads into a single lineage so
`alembic upgrade head` is deterministic and downgrades can target one head.

NOTE (2026-06-22): the third parent ``xcagi_v5_miniprogram`` was removed from
this merge. That revision was never authored (the WeChat mini-program feature
was decommissioned in commit eba145afc) yet was still referenced here, which
left a dangling ``down_revision`` that broke ``alembic`` revision-map loading
entirely. Only the two parents that actually exist remain.

Operational note: ``alembic_version`` must hold only branch tip revision IDs.
If both an ancestor and its descendant are stamped (e.g. ``f0c2a8e1_templates``
and ``xcagi_v5_approval_system``), Alembic raises an overlap error; run
``python scripts/repair_alembic_version_table.py --apply`` from ``FHD/`` to drop
redundant ancestor rows.
"""
from typing import Sequence, Union

revision: str = "f8c2e1d0abb7"
down_revision: Union[str, Sequence[str], None] = (
    "c4a9f8e1d2b3",
    "merge_customers_to_products",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
