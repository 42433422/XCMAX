"""Owned SQLite connections and explicit write transaction boundaries.

These stores use autocommit connections. A connection context manager alone
therefore does not make a multi-statement operation atomic.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from logging import Logger
from pathlib import Path


@dataclass(frozen=True)
class StorageRuntime:
    """Only the public clock, IDs, error policy and logging hooks are late bound."""

    clock: Callable[[], type[datetime]]
    new_id: Callable[[], str]
    log: Callable[[], Logger]
    errors: Callable[[], tuple[type[Exception], ...]]
    sleep: Callable[[float], None]
    now_seconds: Callable[[], float]


def fetch_rows(
    connection: sqlite3.Connection, sql: str, params: Sequence[object] = ()
) -> list[sqlite3.Row]:
    """Materialize a query so callers never yield with a live SQLite cursor."""
    with closing(connection.execute(sql, params)) as cursor:
        return cursor.fetchall()


class SQLiteOwner:
    """One connection per store; the supplied lock also protects memory state."""

    def __init__(self, lock: threading.RLock):
        self.lock = lock
        self.connection: sqlite3.Connection | None = None

    def open(
        self,
        path: str,
        initialize: Callable[[sqlite3.Connection], None],
        *,
        create_parent: bool = False,
    ) -> None:
        if create_parent:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        initialized = False
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL").close()
            connection.execute("PRAGMA synchronous=FULL").close()
            connection.execute("BEGIN IMMEDIATE").close()
            initialize(connection)
            connection.commit()
            self.connection = connection
            initialized = True
        finally:
            if not initialized:
                # Construction owns this connection until it is published.
                connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.lock:
            connection = self.connection
            assert connection is not None
            # Do not silently commit a transaction begun through the legacy
            # private _conn escape hatch. BEGIN fails before any mutation.
            connection.execute("BEGIN IMMEDIATE").close()
            committed = False
            try:
                yield connection
                connection.commit()
                committed = True
            finally:
                if not committed:
                    connection.rollback()

    def rows(self, sql: str, params: Sequence[object] = ()) -> list[sqlite3.Row]:
        with self.lock:
            assert self.connection is not None
            return fetch_rows(self.connection, sql, params)

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection | None]:
        """Use the same mutation boundary for SQLite and in-memory entries."""
        with self.lock:
            if self.connection is None:
                yield None
            else:
                with self.transaction() as connection:
                    yield connection

    def close(self) -> None:
        with self.lock:
            if self.connection is not None:
                self.connection.close()
                # Keep the closed handle: an owned SQLite store must not turn
                # into an empty memory store after close().
