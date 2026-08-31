"""Safe schema bootstrap for a completely empty local SQLite database."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.engine import Connection


def bootstrap_empty_sqlite(connection: Connection, metadata: sa.MetaData) -> bool:
    """Create the current schema only for a genuinely empty SQLite database.

    Historical MODstore migrations before May 2026 intentionally performed
    most DDL only on PostgreSQL.  A fresh local/disaster-recovery SQLite file
    must therefore start from current model metadata before the linear Alembic
    chain adds its audit triggers and revision marker.  Existing databases and
    every non-SQLite deployment remain migration-only.
    """

    if connection.dialect.name != "sqlite":
        return False
    existing = {
        str(name)
        for name in sa.inspect(connection).get_table_names()
        if str(name) != "alembic_version"
    }
    if existing:
        # SQLite inspection starts an implicit SQLAlchemy 2.x transaction.
        # Alembic must own the following migration transaction; otherwise the
        # revision row and DDL are rolled back when this connection closes.
        connection.commit()
        return False
    metadata.create_all(connection)
    # ``create_all`` opens an implicit SQLAlchemy 2.x transaction.  Alembic
    # must begin after it is committed, or SQLite will retain the DDL while
    # rolling back the revision row when the connection closes.
    connection.commit()
    return True


__all__ = ["bootstrap_empty_sqlite"]
