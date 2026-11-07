"""Retain the revision without granting business visibility to every role.

This revision was merged before release but its blanket grants were withdrawn.
Keep the revision identity so databases that recorded it can still traverse the
migration chain. Neither direction can infer which pre-existing grants belong
to this revision, so neither direction changes permissions. Any deployment that
ran the previous implementation needs an administrator's explicit grant audit;
this migration does not silently revoke legitimate permissions.
"""

from __future__ import annotations

from typing import Sequence

revision: str = "2026_11_07_read_tool_permissions"
down_revision: str | Sequence[str] | None = "2026_11_06_purchase_unit_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Do not grant sales/report access implicitly."""


def downgrade() -> None:
    """Do not remove grants whose provenance this revision cannot establish."""
