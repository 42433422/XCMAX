"""Join both slice/stock histories without DDL or a lossy downgrade path."""

import sqlalchemy as sa
from alembic.script import ScriptDirectory

from alembic import op

revision = "2026_11_15_delivery_slices_merge"
down_revision = ("2026_11_15_stock_posting_key", "2026_11_15_etl_source_slices")
branch_labels = None
depends_on = None


def upgrade():
    pass


def _run_rows_table(inspector) -> str | None:
    names = set(inspector.get_table_names())
    if "elt_run_rows" in names:
        return "elt_run_rows"
    if "etl_run_rows" in names:
        return "etl_run_rows"
    return None


def downgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    table = _run_rows_table(inspector)
    if table is None:
        return
    if "source_slice" not in {column["name"] for column in inspector.get_columns(table)}:
        return
    # Refuse before Alembic traverses either historical branch. The old split
    # revision cannot be rewritten and its downgrade predates this safeguard.
    if connection.execute(
        sa.text(f"SELECT 1 FROM {table} WHERE source_slice != 0 OR source_slice IS NULL LIMIT 1")
    ).first():
        raise RuntimeError(
            "Cannot downgrade delivery histories without losing ELT slice provenance"
        )

    # Both published parents independently own the source-slice DDL. Even zero
    # rows must not be downgraded to a stamp whose required column was removed
    # by the other parent's historical downgrade. Full common-ancestor rollback
    # remains lossless and is exercised from both upgrade histories.
    context = op.get_context()
    script = ScriptDirectory.from_config(context.config)
    safe = {
        revision.revision for revision in script.walk_revisions(head="2026_11_11_agent_permissions")
    }
    if context.opts.get("destination_rev") not in safe | {"base"}:
        raise RuntimeError(
            "Cannot partially downgrade merged delivery histories; use a common ancestor"
        )
