from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260723_knowledge_chunk_config.py"
    )
    spec = importlib.util.spec_from_file_location("knowledge_chunk_config_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Ops:
    def __init__(self) -> None:
        self.added = []
        self.dropped = []

    def add_column(self, table, column) -> None:
        self.added.append((table, column))

    def drop_column(self, table, column) -> None:
        self.dropped.append((table, column))


def test_upgrade_adds_chunk_config_once(monkeypatch) -> None:
    migration = _load_migration()
    ops = _Ops()
    monkeypatch.setattr(migration, "op", ops)
    monkeypatch.setattr(migration, "_table_exists", lambda table: table == "knowledge_collections")
    monkeypatch.setattr(migration, "_column_exists", lambda _table, _column: False)

    migration.upgrade()

    assert len(ops.added) == 1
    table, column = ops.added[0]
    assert table == "knowledge_collections"
    assert column.name == "chunk_config"
    assert column.nullable is True
    assert str(column.type) == "TEXT"


def test_upgrade_and_downgrade_are_idempotent(monkeypatch) -> None:
    migration = _load_migration()
    ops = _Ops()
    monkeypatch.setattr(migration, "op", ops)
    monkeypatch.setattr(migration, "_table_exists", lambda _table: True)
    monkeypatch.setattr(migration, "_column_exists", lambda _table, _column: True)

    migration.upgrade()
    migration.downgrade()

    assert ops.added == []
    assert ops.dropped == [("knowledge_collections", "chunk_config")]
