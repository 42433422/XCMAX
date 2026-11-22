"""The existing Alembic chain preserves identity and evidence on repeat upgrade."""

import importlib.util
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa

from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_life_migration_is_idempotent_and_preserves_state(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261121_xiaoc_life.py"
    spec = importlib.util.spec_from_file_location("life_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'migration.sqlite'}")
    with engine.begin() as connection:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.upgrade()
        connection.execute(
            sa.text("INSERT INTO xiaoc_life_state VALUES (:id, :version, :state, :now)"),
            {
                "id": "enterprise-life",
                "version": 11,
                "state": '{"level":5}',
                "now": datetime(2026, 11, 21).isoformat(),
            },
        )
        module.upgrade()
        row = connection.execute(
            sa.text("SELECT identity_id, version, state_json FROM xiaoc_life_state")
        ).one()
        assert tuple(row) == ("enterprise-life", 11, '{"level":5}')
        assert len(sa.inspect(connection).get_indexes("xiaoc_life_events")) == 1
        module.downgrade()
        module.downgrade()
        assert not sa.inspect(connection).has_table("xiaoc_life_state")
    engine.dispose()
