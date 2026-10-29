"""Add isolated original archive metadata without changing existing retention."""

from __future__ import annotations

from alembic import op
from app.db.models.etl_archive import EtlArchiveAsset, EtlArchiveQuota, EtlArchiveVersion

revision = "2026_10_29_etl_archive"
down_revision = "2026_10_20_refund_permission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for model in (EtlArchiveQuota, EtlArchiveAsset, EtlArchiveVersion):
        model.__table__.create(bind, checkfirst=True)


def downgrade() -> None:
    # Archived originals and their references must not be destroyed on downgrade.
    pass
