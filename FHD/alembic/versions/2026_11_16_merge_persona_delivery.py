"""收口 delivery 与 persona 两条迁移头"""

import sqlalchemy as sa
from alembic.script import ScriptDirectory

from alembic import op

revision = "2026_11_16_merge_persona_delivery"
down_revision = ("2026_11_15_delivery_slices_merge", "2026_11_16_persona_account_key")
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
    # 现行头在 delivery 合并之后。回退必须先按当前运行行表检查切片来源，
    # 并拒绝停在任一父头上，避免版本戳与表结构再次分叉。
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    table = _run_rows_table(inspector)
    if table is not None:
        columns = {column["name"] for column in inspector.get_columns(table)}
        if (
            "source_slice" in columns
            and connection.execute(
                sa.text(
                    f"SELECT 1 FROM {table} WHERE source_slice != 0 OR source_slice IS NULL LIMIT 1"
                )
            ).first()
        ):
            raise RuntimeError(
                "Cannot downgrade delivery histories without losing ELT slice provenance"
            )
    context = op.get_context()
    script = ScriptDirectory.from_config(context.config)
    safe = {
        revision.revision for revision in script.walk_revisions(head="2026_11_11_agent_permissions")
    }
    if context.opts.get("destination_rev") not in safe | {"base"}:
        raise RuntimeError(
            "Cannot partially downgrade merged delivery histories; use a common ancestor"
        )
