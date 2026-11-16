"""Forward-only cutover of persisted ELT identifier values.

Historical revision IDs and already-applied migration files are unchanged.
This upgrade rewrites business-mutable state so runtime code can stop reading
legacy ETL identifiers. Issued receipts and dedicated audit logs are left as
historical evidence and are not rewritten.
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic.script import ScriptDirectory

from alembic import op

revision = "2026_11_16_elt_value_cutover"
down_revision = "2026_11_16_elt_permission_cutover"
branch_labels = None
depends_on = None

VALUE_MAP = {
    "shipment_excel_etl": "shipment_excel_elt",
    "shipment_delivery_etl": "shipment_delivery_elt",
    "general_etl": "general_elt",
    "execute_delivery_etl": "execute_delivery_elt",
}
KEY_MAP = {"_etl": "_elt"}
RAW_TEXT_MAP = {
    "source=shipment_excel_etl": "source=shipment_excel_elt",
    "source_kind=general_etl": "source_kind=general_elt",
}

# Operational JSON used to resume or roll back a run. receipt/summary remain historical.
_JSON_COLUMNS = (
    ("elt_run_rows", ("after_json", "before_json")),
    ("elt_runs", ("draft_json",)),
    ("shipment_elt_import_fingerprints", ("meta_json",)),
    ("templates", ("analyzed_data", "editable_config", "business_rules")),
)


class EltValueCutoverConflict(RuntimeError):
    """Raised when old and new keys both exist with incompatible values."""


def _rewrite_string(value: str) -> str:
    return VALUE_MAP.get(value, value)


def _merge_mapped_key(container: dict, old_key: str, new_key: str) -> None:
    if old_key not in container:
        return
    old_value = container[old_key]
    if new_key not in container:
        container[new_key] = old_value
        del container[old_key]
        return
    new_value = container[new_key]
    if old_value == new_value:
        del container[old_key]
        return
    if isinstance(old_value, dict) and isinstance(new_value, dict):
        leftover: dict = {}
        for key, item in old_value.items():
            if key not in new_value:
                new_value[key] = item
            elif new_value[key] != item:
                leftover[key] = item
        if leftover:
            raise EltValueCutoverConflict(
                f"无法合并 JSON 键 {old_key} 与 {new_key}：存在冲突字段 {sorted(leftover)}"
            )
        del container[old_key]
        return
    raise EltValueCutoverConflict(f"无法合并 JSON 键 {old_key} 与 {new_key}：值不一致")


def rewrite_data(value):
    if isinstance(value, dict):
        rewritten = {key: rewrite_data(item) for key, item in value.items()}
        for old_key, new_key in KEY_MAP.items():
            _merge_mapped_key(rewritten, old_key, new_key)
        return rewritten
    if isinstance(value, list):
        return [rewrite_data(item) for item in value]
    if isinstance(value, str):
        return _rewrite_string(value)
    return value


def rewrite_json_text(raw: str | None) -> tuple[str | None, bool]:
    if raw is None or not str(raw).strip():
        return raw, False
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return raw, False
    rewritten = rewrite_data(parsed)
    if rewritten == parsed:
        return raw, False
    return json.dumps(rewritten, ensure_ascii=False), True


def rewrite_raw_text(raw: str | None) -> tuple[str | None, bool]:
    if raw is None:
        return raw, False
    text = str(raw)
    updated = text
    for old, new in RAW_TEXT_MAP.items():
        updated = updated.replace(old, new)
    return updated, updated != text


def _table_columns(inspector, name: str) -> set[str]:
    if name not in set(inspector.get_table_names()):
        return set()
    return {column["name"] for column in inspector.get_columns(name)}


def _rewrite_columns(bind, table: str, columns: tuple[str, ...], pk: str) -> None:
    inspector = sa.inspect(bind)
    present = _table_columns(inspector, table)
    if not present or pk not in present:
        return
    existing = [column for column in columns if column in present]
    if not existing:
        return
    cols_sql = ", ".join([pk, *existing])
    rows = bind.execute(sa.text(f"SELECT {cols_sql} FROM {table}")).mappings().all()
    for row in rows:
        updates: dict[str, str | None] = {}
        for column in existing:
            rewritten, changed = rewrite_json_text(row[column])
            if changed:
                updates[column] = rewritten
        if not updates:
            continue
        assignments = ", ".join(f"{column} = :{column}" for column in updates)
        bind.execute(
            sa.text(f"UPDATE {table} SET {assignments} WHERE {pk} = :pk"),
            {**updates, "pk": row[pk]},
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    fingerprint_tables = [
        name
        for name in ("shipment_elt_import_fingerprints", "shipment_etl_import_fingerprints")
        if name in set(inspector.get_table_names())
    ]
    for table in fingerprint_tables:
        columns = _table_columns(inspector, table)
        if "source_kind" in columns:
            bind.execute(
                sa.text(
                    f"UPDATE {table} SET source_kind = 'general_elt' "
                    "WHERE source_kind = 'general_etl'"
                )
            )

    for table, columns in _JSON_COLUMNS:
        pk = "id"
        _rewrite_columns(bind, table, columns, pk)

    shipment_cols = _table_columns(inspector, "shipment_records")
    if "raw_text" in shipment_cols and "id" in shipment_cols:
        rows = bind.execute(sa.text("SELECT id, raw_text FROM shipment_records")).mappings().all()
        for row in rows:
            rewritten, changed = rewrite_raw_text(row["raw_text"])
            if changed:
                bind.execute(
                    sa.text("UPDATE shipment_records SET raw_text = :raw_text WHERE id = :id"),
                    {"raw_text": rewritten, "id": row["id"]},
                )
        if "parsed_data" in shipment_cols:
            _rewrite_columns(bind, "shipment_records", ("parsed_data",), "id")


def _run_rows_table(inspector) -> str | None:
    names = set(inspector.get_table_names())
    if "elt_run_rows" in names:
        return "elt_run_rows"
    if "etl_run_rows" in names:
        return "etl_run_rows"
    return None


def downgrade() -> None:
    """Keep migrated values. Still refuse a lossy or partial delivery downgrade."""
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
