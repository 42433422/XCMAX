"""Recover interrupted SQLite DDL without losing already persisted follow-up cursors."""

from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

import pytest
import sqlalchemy as sa

from alembic.migration import MigrationContext
from alembic.operations import Operations


@pytest.mark.parametrize("existing", ["none", "model", "interrupted"])
def test_followup_migration_repairs_index_and_preserves_existing_rows(
    tmp_path, monkeypatch, existing
):
    source = Path(__file__).resolve().parents[1] / "alembic/versions/20261119_xiaoc_followups.py"
    spec = importlib.util.spec_from_file_location("xiaoc_followup_migration", source)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'migration.sqlite'}")
    with engine.begin() as db:
        db.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        db.execute(sa.text("CREATE TABLE customer_service_tickets (id INTEGER PRIMARY KEY)"))
        db.execute(sa.text("INSERT INTO users VALUES (7)"))
        db.execute(sa.text("INSERT INTO customer_service_tickets VALUES (21)"))
    if existing == "interrupted":
        with pytest.raises(RuntimeError, match="interrupted"), engine.begin() as db:
            operations = Operations(MigrationContext.configure(db))
            monkeypatch.setattr(migration, "op", operations)

            def interrupted_index(*args, **kwargs):
                raise RuntimeError("interrupted before due index")

            monkeypatch.setattr(operations, "create_index", interrupted_index)
            migration.upgrade()
        assert sa.inspect(engine).has_table(migration.TABLE)
        assert sa.inspect(engine).get_indexes(migration.TABLE) == []
    elif existing == "model":
        from modstore_server.models import Base

        Base.metadata.tables[migration.TABLE].create(engine)

    with engine.begin() as db:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(db)))
        if existing == "none":
            migration.upgrade()
        table = sa.Table(migration.TABLE, sa.MetaData(), autoload_with=db)
        row = {
            "user_id": 7,
            "ticket_id": 21,
            "following": False,
            "last_observed": "a" * 64,
            "next_check_at": datetime(2026, 11, 19, 12),
            "version": 9,
        }
        db.execute(table.insert().values(**row))
        migration.upgrade()
        migration.upgrade()
        assert dict(db.execute(sa.select(table)).one()._mapping) == row
        inspector = sa.inspect(db)
        assert inspector.get_pk_constraint(migration.TABLE)["constrained_columns"] == [
            "user_id",
            "ticket_id",
        ]
        assert len(inspector.get_foreign_keys(migration.TABLE)) == 2
        assert inspector.get_indexes(migration.TABLE) == [
            {
                "name": migration.INDEX,
                "column_names": ["following", "next_check_at"],
                "unique": 0,
                "dialect_options": {},
            }
        ]
        migration.downgrade()
        migration.downgrade()
        assert not sa.inspect(db).has_table(migration.TABLE)
        assert db.scalar(sa.text("SELECT count(*) FROM users")) == 1
        assert db.scalar(sa.text("SELECT count(*) FROM customer_service_tickets")) == 1
    engine.dispose()
