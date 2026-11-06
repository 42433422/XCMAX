"""Lock versions upgrade legacy rows and preserve databases patched before Alembic."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa

from alembic.migration import MigrationContext
from alembic.operations import Operations


@pytest.mark.parametrize("existing_version", [None, 7])
def test_lock_version_upgrade_is_idempotent_and_preserves_rows(monkeypatch, existing_version):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261107_ticket_lock_version.py"
    spec = importlib.util.spec_from_file_location("ticket_lock_version_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        metadata = sa.MetaData()
        for name in ("customer_service_tickets", "customer_service_actions"):
            columns = [sa.Column("id", sa.Integer(), primary_key=True)]
            if existing_version is not None:
                columns.append(
                    sa.Column("lock_version", sa.Integer(), nullable=False, server_default="0")
                )
            table = sa.Table(name, metadata, *columns)
            table.create(connection)
            row = {"id": 1}
            if existing_version is not None:
                row["lock_version"] = existing_version
            connection.execute(table.insert().values(**row))

        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        migration.upgrade()
        for name in ("customer_service_tickets", "customer_service_actions"):
            table = sa.Table(name, sa.MetaData(), autoload_with=connection)
            assert table.c.lock_version.nullable is False
            assert connection.scalar(sa.select(table.c.lock_version)) == (existing_version or 0)
            connection.execute(table.insert().values(id=2))
            assert connection.scalar(sa.select(table.c.lock_version).where(table.c.id == 2)) == 0
        migration.downgrade()
        for name in ("customer_service_tickets", "customer_service_actions"):
            table = sa.Table(name, sa.MetaData(), autoload_with=connection)
            assert "lock_version" not in table.c
            assert connection.scalars(sa.select(table.c.id).order_by(table.c.id)).all() == [1, 2]
    engine.dispose()
