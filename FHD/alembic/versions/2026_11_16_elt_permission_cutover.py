"""Persist leftover etl.* permission codes as elt.*; do not alias at runtime.

Revision identifiers are new. Historical revisions that already renamed tables
or some permission rows are left unchanged. This upgrade is idempotent and
merges a leftover etl.* row into an existing elt.* row when both are present.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic.script import ScriptDirectory

from alembic import op

revision = "2026_11_16_elt_permission_cutover"
down_revision = "2026_11_16_merge_persona_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "permissions" not in tables:
        return
    columns = {column["name"] for column in inspector.get_columns("permissions")}
    if "code" not in columns:
        return
    has_module = "module" in columns
    has_roles = "role_permissions" in tables
    rows = (
        bind.execute(sa.text("SELECT id, code FROM permissions WHERE code LIKE 'etl.%'"))
        .mappings()
        .all()
    )
    for row in rows:
        new_code = "elt." + str(row["code"])[4:]
        existing = bind.execute(
            sa.text("SELECT id FROM permissions WHERE code = :code"),
            {"code": new_code},
        ).first()
        if existing is None:
            if has_module:
                bind.execute(
                    sa.text(
                        "UPDATE permissions SET code = :new_code, "
                        "module = CASE WHEN module = 'etl' THEN 'elt' ELSE module END "
                        "WHERE id = :id"
                    ),
                    {"new_code": new_code, "id": row["id"]},
                )
            else:
                bind.execute(
                    sa.text("UPDATE permissions SET code = :new_code WHERE id = :id"),
                    {"new_code": new_code, "id": row["id"]},
                )
            continue
        if has_roles:
            # Keep already-granted elt.* links; move any unique leftover grants, then drop the old row.
            bind.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_id, permission_id) "
                    "SELECT role_id, :new_id FROM role_permissions "
                    "WHERE permission_id = :old_id AND role_id NOT IN "
                    "(SELECT role_id FROM role_permissions WHERE permission_id = :new_id)"
                ),
                {"new_id": existing[0], "old_id": row["id"]},
            )
            bind.execute(
                sa.text("DELETE FROM role_permissions WHERE permission_id = :old_id"),
                {"old_id": row["id"]},
            )
        bind.execute(sa.text("DELETE FROM permissions WHERE id = :id"), {"id": row["id"]})
    leftover = bind.execute(sa.text("SELECT code FROM permissions WHERE code LIKE 'etl.%'")).first()
    if leftover:
        raise RuntimeError(
            "权限升级未完成，仍有历史 etl.* 权限码："
            + str(leftover[0])
            + "。请修复后重新执行 alembic upgrade。"
        )


def _run_rows_table(inspector) -> str | None:
    names = set(inspector.get_table_names())
    if "elt_run_rows" in names:
        return "elt_run_rows"
    if "etl_run_rows" in names:
        return "etl_run_rows"
    return None


def downgrade() -> None:
    """Keep elt.* permission codes. Still refuse a lossy or partial delivery downgrade."""
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
