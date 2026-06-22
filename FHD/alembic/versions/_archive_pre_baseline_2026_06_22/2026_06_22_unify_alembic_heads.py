"""unify alembic heads (single deterministic head)

Revision ID: 2026_06_22_unify_heads
Revises: 2026_06_07_sessions_tenant, 2026_06_07_audit_ts, xcagi_v4_inventory_purchase
Create Date: 2026-06-22

No-op merge that collapses the remaining branch tips into one head so
``alembic upgrade head`` / ``alembic check`` are deterministic again.

Background: the FHD/alembic lineage had drifted to 4 heads plus 2 dangling
``down_revision`` references (``xcagi_v5_miniprogram`` and
``2026_06_02_tenant_rbac``, neither ever authored), which made the revision map
fail to load at all. After repairing those two references, three real branch
tips remained:

  * 2026_06_07_sessions_tenant        (sessions.tenant_id)
  * 2026_06_07_audit_ts               (audit timestamp backfill)
  * xcagi_v4_inventory_purchase       (inventory/purchase tables)

This migration merges them. It performs no schema changes.
"""
from typing import Sequence, Union

revision: str = "2026_06_22_unify_heads"
down_revision: Union[str, Sequence[str], None] = (
    "2026_06_07_sessions_tenant",
    "2026_06_07_audit_ts",
    "xcagi_v4_inventory_purchase",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
