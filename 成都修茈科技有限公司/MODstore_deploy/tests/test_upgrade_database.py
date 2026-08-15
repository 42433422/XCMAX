from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from scripts.upgrade_database import LEGACY_BASELINE_COLUMNS, legacy_baseline_gaps


class _Inspector:
    def __init__(self, columns: dict[str, set[str]]) -> None:
        self.columns = columns

    def get_table_names(self) -> list[str]:
        return list(self.columns)

    def get_columns(self, table_name: str) -> list[dict[str, object]]:
        return [{"name": name} for name in self.columns[table_name]]


def _complete_baseline() -> dict[str, set[str]]:
    return {table: set(columns) for table, columns in LEGACY_BASELINE_COLUMNS.items()}


def test_legacy_baseline_accepts_complete_schema() -> None:
    assert legacy_baseline_gaps(_Inspector(_complete_baseline())) == []


def test_legacy_baseline_fails_closed_for_missing_table_and_column() -> None:
    columns = _complete_baseline()
    columns.pop("employee_trigger_bindings")
    columns["users"].remove("is_enterprise")

    assert legacy_baseline_gaps(_Inspector(columns)) == [
        "users.is_enterprise",
        "employee_trigger_bindings",
    ]


def test_account_lifecycle_backfill_uses_cross_dialect_booleans() -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/20260815_account_registration_lifecycle.py"
    )
    spec = importlib.util.spec_from_file_location(
        "account_lifecycle_migration", migration_path
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    executed: list[object] = []
    migration._columns = lambda: {"account_state", "is_admin", "is_enterprise"}
    migration._indexes = lambda: {"ix_users_account_state"}
    migration.op = SimpleNamespace(execute=executed.append)

    migration.upgrade()

    assert len(executed) == 1
    sql = str(
        executed[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "users.is_admin IS true" in sql
    assert "users.is_enterprise IS true" in sql
