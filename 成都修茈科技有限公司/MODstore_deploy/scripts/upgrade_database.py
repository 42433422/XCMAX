"""Upgrade the MODstore database and safely adopt the legacy schema baseline."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from sqlalchemy import Column, MetaData, String, Table, create_engine, inspect, text
from sqlalchemy.engine import Engine

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

LEGACY_BASELINE_REVISION = "20260512_consolidate_init_db_columns"
LEGACY_BASELINE_COLUMNS: dict[str, frozenset[str]] = {
    "users": frozenset({"default_llm_json", "experience", "is_enterprise", "phone"}),
    "catalog_items": frozenset(
        {
            "compliance_status",
            "delist_reason",
            "description_embedding",
            "graph_snapshot",
            "industry",
            "industry_code",
            "industry_secondary",
            "install_count",
            "ip_risk_level",
            "license_scope",
            "material_category",
            "origin_type",
            "rank_score",
            "security_level",
            "template_category",
            "template_difficulty",
        }
    ),
    "workflows": frozenset({"kind", "migrated_to_id", "migration_status"}),
    "user_plans": frozenset({"auto_renew", "renewal_fail_reason"}),
    "knowledge_collections": frozenset({"embedding_provider", "embedding_source"}),
    "account_experience_ledger": frozenset({"description"}),
    "employee_change_requests": frozenset(
        {
            "approval_required_globs_json",
            "base_commit_sha",
            "git_branch",
            "staged_commit_sha",
        }
    ),
    "employee_trigger_bindings": frozenset({"priority"}),
    "ai_employee_accounts": frozenset({"id"}),
    "user_studio_assets": frozenset({"id"}),
    "event_outbox_dlq": frozenset({"id"}),
}


class SchemaInspector(Protocol):
    def get_table_names(self) -> list[str]: ...

    def get_columns(self, table_name: str) -> list[dict[str, object]]: ...


def legacy_baseline_gaps(schema: SchemaInspector) -> list[str]:
    """Return stable, non-sensitive identifiers missing from the legacy baseline."""

    tables = set(schema.get_table_names())
    gaps: list[str] = []
    for table, required_columns in LEGACY_BASELINE_COLUMNS.items():
        if table not in tables:
            gaps.append(table)
            continue
        actual_columns = {str(item["name"]) for item in schema.get_columns(table)}
        gaps.extend(f"{table}.{column}" for column in sorted(required_columns - actual_columns))
    return gaps


def _database_url() -> str:
    url = (os.environ.get("MODSTORE_DATABASE_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        raise RuntimeError("database_url_missing")
    if url.startswith("postgres://"):
        return "postgresql://" + url.removeprefix("postgres://")
    return url


def _ensure_version_table_capacity(engine: Engine) -> None:
    """Create/expand Alembic's version table for the existing long revision ids."""

    metadata = MetaData()
    Table(
        "alembic_version",
        metadata,
        Column("version_num", String(128), nullable=False, primary_key=True),
    )
    metadata.create_all(engine, checkfirst=True)
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)")
            )


def upgrade_database(config_path: Path) -> tuple[str, ...]:
    """Adopt a verified legacy baseline, upgrade all heads, and prove the result."""

    configuration = Config(str(config_path))
    configuration.set_main_option("script_location", str(config_path.parent / "alembic"))
    expected_heads = set(ScriptDirectory.from_config(configuration).get_heads())
    engine = create_engine(_database_url())
    try:
        schema = inspect(engine)
        if "alembic_version" not in set(schema.get_table_names()):
            gaps = legacy_baseline_gaps(schema)
            if gaps:
                raise RuntimeError("legacy_schema_baseline_mismatch:" + ",".join(gaps))
            _ensure_version_table_capacity(engine)
            command.stamp(configuration, LEGACY_BASELINE_REVISION)
        else:
            _ensure_version_table_capacity(engine)

        command.upgrade(configuration, "heads")
        with engine.connect() as connection:
            current_heads = set(MigrationContext.configure(connection).get_current_heads())
    finally:
        engine.dispose()

    if current_heads != expected_heads:
        raise RuntimeError(
            "schema_migration_head_mismatch:"
            f"current={sorted(current_heads)},expected={sorted(expected_heads)}"
        )
    return tuple(sorted(current_heads))


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    heads = upgrade_database(root / "alembic.ini")
    print("schema migration verified heads=" + ",".join(heads))


if __name__ == "__main__":
    main()
