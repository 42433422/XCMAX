from __future__ import annotations

import sqlalchemy as sa

from modstore_server.db.alembic_bootstrap import bootstrap_empty_sqlite


def _metadata_with_target() -> sa.MetaData:
    metadata = sa.MetaData()
    sa.Table("target_table", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    return metadata


def test_empty_sqlite_receives_current_schema() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.connect() as connection:
        created = bootstrap_empty_sqlite(connection, _metadata_with_target())

        assert created is True
        assert connection.in_transaction() is False
        assert sa.inspect(connection).has_table("target_table") is True


def test_existing_sqlite_is_never_rebased_from_metadata() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.connect() as connection:
        connection.execute(sa.text("CREATE TABLE existing_table (id INTEGER PRIMARY KEY)"))
        connection.commit()
        created = bootstrap_empty_sqlite(connection, _metadata_with_target())

        assert created is False
        assert connection.in_transaction() is False
        assert sa.inspect(connection).has_table("target_table") is False
