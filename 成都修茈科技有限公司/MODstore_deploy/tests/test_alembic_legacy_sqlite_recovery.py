from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import sqlalchemy as sa


def _load_migration(monkeypatch):
    alembic_module = types.ModuleType("alembic")
    alembic_module.op = types.SimpleNamespace()
    monkeypatch.setitem(sys.modules, "alembic", alembic_module)
    migration = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260512_consolidate_init_db_columns.py"
    )
    spec = importlib.util.spec_from_file_location("legacy_column_recovery_migration", migration)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_legacy_table_is_skipped(monkeypatch) -> None:
    module = _load_migration(monkeypatch)
    engine = sa.create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        monkeypatch.setattr(module.op, "get_bind", lambda: connection, raising=False)

        def unexpected_add_column(*_args, **_kwargs) -> None:
            raise AssertionError("missing legacy table must not be altered")

        monkeypatch.setattr(module.op, "add_column", unexpected_add_column, raising=False)

        module._add_col(
            "knowledge_collections",
            "embedding_provider",
            sa.Column("embedding_provider", sa.String(64)),
        )


def test_existing_legacy_table_receives_missing_column(monkeypatch) -> None:
    module = _load_migration(monkeypatch)
    engine = sa.create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE knowledge_collections (id INTEGER PRIMARY KEY)"))
        monkeypatch.setattr(module.op, "get_bind", lambda: connection, raising=False)

        def add_column(table: str, column: sa.Column) -> None:
            connection.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {column.name} VARCHAR(64)"))

        monkeypatch.setattr(module.op, "add_column", add_column, raising=False)
        module._add_col(
            "knowledge_collections",
            "embedding_provider",
            sa.Column("embedding_provider", sa.String(64)),
        )

        columns = {
            row[1]
            for row in connection.execute(sa.text("PRAGMA table_info(knowledge_collections)"))
        }
        assert "embedding_provider" in columns
