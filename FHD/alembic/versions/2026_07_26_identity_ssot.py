"""Reconcile account identity snapshots to users.tier.

Revision ID: 2026_07_26_identity_ssot
Revises: 2026_07_24_shipment_etl_fingerprints
Create Date: 2026-07-26
"""

from __future__ import annotations

from typing import Sequence

from alembic import op

revision: str = "2026_07_26_identity_ssot"
down_revision: str | Sequence[str] | None = "2026_07_24_shipment_etl_fingerprints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Market identity is an external attestation, but User.tier is the durable
    # local identity SSOT. Promote the user first, then rebuild the session
    # snapshot. Never derive identity from a client-selected login entrance.
    # Preserve local administrators that older SessionManager versions derived
    # from User.role before tier became authoritative.
    op.execute(
        """
        UPDATE users
        SET tier = 'admin'
        WHERE LOWER(COALESCE(role, '')) IN ('admin', 'super_admin', 'owner')
        """
    )
    op.execute(
        """
        UPDATE users
        SET tier = 'admin'
        WHERE tier <> 'admin'
          AND id IN (
              SELECT user_id FROM sessions
              WHERE COALESCE(market_is_admin, FALSE)
          )
        """
    )
    op.execute(
        """
        UPDATE users
        SET tier = 'enterprise'
        WHERE COALESCE(tier, '') NOT IN ('admin', 'enterprise')
          AND id IN (
              SELECT user_id FROM sessions
              WHERE COALESCE(market_is_enterprise, FALSE)
          )
        """
    )
    op.execute(
        """
        UPDATE sessions
        SET account_kind = CASE
            WHEN EXISTS (
                SELECT 1 FROM users
                WHERE users.id = sessions.user_id AND users.tier = 'admin'
            ) THEN 'admin'
            WHEN EXISTS (
                SELECT 1 FROM users
                WHERE users.id = sessions.user_id AND users.tier = 'enterprise'
            ) THEN 'enterprise'
            ELSE 'personal'
        END
        """
    )


def downgrade() -> None:
    # Identity promotions are security-relevant business data and must not be
    # guessed away on downgrade. The snapshot remains a valid audit value.
    pass
