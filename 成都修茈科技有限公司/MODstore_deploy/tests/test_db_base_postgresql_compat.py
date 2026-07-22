from __future__ import annotations

from types import SimpleNamespace

from modstore_server.db.base import _add_column_if_missing


class _MissingColumnResult:
    def first(self):
        return None


class _Connection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement, parameters=None):
        self.statements.append(str(statement))
        return _MissingColumnResult()


class _Transaction:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def __enter__(self) -> _Connection:
        return self.connection

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


class _PostgresqlEngine:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self) -> None:
        self.connection = _Connection()

    def begin(self) -> _Transaction:
        return _Transaction(self.connection)


def test_postgresql_compat_column_translates_datetime_to_timestamp() -> None:
    engine = _PostgresqlEngine()

    _add_column_if_missing(engine, "event_outbox_dlq", "resolved_at", "DATETIME")

    assert engine.connection.statements[-1] == (
        "ALTER TABLE event_outbox_dlq ADD COLUMN resolved_at TIMESTAMP WITHOUT TIME ZONE"
    )
