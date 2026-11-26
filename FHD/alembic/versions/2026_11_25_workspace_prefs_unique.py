"""Migrate identical legacy preference duplicates before enforcing owner/key uniqueness.

Conflicting values cannot be resolved from row order without risking lost user
settings. In that case stop the upgrade and require an explicit reconciliation.
"""

import sqlalchemy as sa

from alembic import op

revision = "2026_11_25_workspace_prefs_unique"
down_revision = "2026_11_24_trial_session"
branch_labels = None
depends_on = None

_INDEX = "uq_user_preferences_owner_key"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "user_preferences" not in inspector.get_table_names():
        raise RuntimeError("user_preferences_missing_before_unique_migration")

    duplicates = bind.execute(
        sa.text(
            "SELECT user_id, preference_key FROM user_preferences "
            "GROUP BY user_id, preference_key HAVING COUNT(*) > 1"
        )
    ).all()
    # Preflight all groups before modifying a single row. Do not silently
    # choose a winner for conflicting values or overwrite settings.
    remove_ids: list[int] = []
    for user_id, preference_key in duplicates:
        rows = bind.execute(
            sa.text(
                "SELECT id, preference_value FROM user_preferences "
                "WHERE user_id = :owner AND preference_key = :key ORDER BY id"
            ),
            {"owner": user_id, "key": preference_key},
        ).all()
        if len({value for _, value in rows}) != 1:
            raise RuntimeError(
                "conflicting_legacy_user_preferences_requires_reconciliation"
            )
        remove_ids.extend(row_id for row_id, _ in rows[1:])

    for row_id in remove_ids:
        bind.execute(sa.text("DELETE FROM user_preferences WHERE id = :id"), {"id": row_id})

    # The squashed baseline imports current ORM metadata on fresh databases,
    # so the model may have created the index before this revision runs.
    if _INDEX not in {index["name"] for index in sa.inspect(bind).get_indexes("user_preferences")}:
        op.create_index(
            _INDEX, "user_preferences", ["user_id", "preference_key"], unique=True
        )


def downgrade() -> None:
    # Do not reopen the risk of duplicate tenant settings during rollback.
    raise RuntimeError("workspace_preference_uniqueness_downgrade_blocked")
